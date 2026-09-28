"""One speech-to-text session over the Gradium ASR WebSocket.

The caller's audio (HA sends 10 ms chunks) is regrouped into 80 ms frames and
forwarded as it arrives. When the caller's stream ends (HA's VAD saw the end
of speech), a flush is sent right away, without silent drain frames: measured
on the real API, the transcript is complete either way and comes back about
230 ms sooner. The server's own end_of_stream is not awaited, it only comes
several hundred milliseconds later.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterable
from typing import Any

import aiohttp

from .const import FLUSH_ID, STT_INPUT_FORMAT, STT_PATH
from .errors import GradiumServerError, GradiumTimeoutError
from .models import Endpoint, SttSettings, Timeouts
from .pcm import PcmFramer
from .socket import GradiumSocket
from .tasks import stop_task


class GradiumSttSession:
    """Drive one ASR WebSocket from setup to the flushed transcript."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        endpoint: Endpoint,
        timeouts: Timeouts,
        settings: SttSettings,
    ) -> None:
        """Store what the session needs; nothing is opened yet."""
        self._session = session
        self._api_key = api_key
        self._url = f"{endpoint.ws_base}{STT_PATH}"
        self._timeouts = timeouts
        self._settings = settings
        self._segments: list[str] = []
        self._flushed = asyncio.Event()

    async def run(self, audio: AsyncIterable[bytes]) -> str:
        """Stream the audio and return the stripped transcript, "" when nothing was heard."""
        socket = await GradiumSocket.connect(
            self._session, self._url, self._api_key, self._timeouts
        )
        reader: asyncio.Task[None] | None = None
        try:
            await self._setup(socket)
            reader = asyncio.create_task(self._read(socket), name="gradium-stt-reader")
            await self._send_audio(socket, audio, reader)
            await socket.send({"type": "flush", "flush_id": FLUSH_ID})
            await self._wait_flushed(reader)
            await socket.send({"type": "end_of_stream"})
        finally:
            await stop_task(reader)
            await socket.close()
        return " ".join(self._segments).strip()

    async def _setup(self, socket: GradiumSocket) -> None:
        """Send the setup message and check the ready answer."""
        await socket.send(
            {
                "type": "setup",
                "model_name": self._settings.model_name,
                "input_format": STT_INPUT_FORMAT,
                "json_config": {
                    "language": self._settings.language,
                    "delay_in_frames": self._settings.delay_in_frames,
                },
            }
        )
        ready = await socket.receive(self._timeouts.ready, phase="ready")
        if ready.get("type") != "ready":
            raise GradiumServerError(
                f"Gradium ASR answered the setup with {ready.get('type')!r} instead of ready"
            )

    async def _read(self, socket: GradiumSocket) -> None:
        """Collect transcript segments until the flush is confirmed.

        Returns on `flushed` (or on an early server end_of_stream); any error
        ends the task with that error, which the sender side re-raises.
        """
        while True:
            message = await socket.receive(None)
            kind = message.get("type")
            if kind == "text":
                self._append(message.get("text"))
            elif kind == "flushed" and message.get("flush_id") == FLUSH_ID:
                self._append(message.get("text"))
                self._flushed.set()
                return
            elif kind == "end_of_stream":
                return

    async def _send_audio(
        self, socket: GradiumSocket, audio: AsyncIterable[bytes], reader: asyncio.Task[None]
    ) -> None:
        """Forward the caller's audio as fixed-size frames, the last one zero-padded."""
        framer = PcmFramer()
        async for chunk in audio:
            for frame in framer.push(chunk):
                await self._send_frame(socket, frame, reader)
        last = framer.finish()
        if last is not None:
            await self._send_frame(socket, last, reader)

    async def _send_frame(
        self, socket: GradiumSocket, frame: bytes, reader: asyncio.Task[None]
    ) -> None:
        """Send one frame, unless the reader has already ended the session."""
        if reader.done():
            reader.result()
            raise GradiumServerError("Gradium ASR ended the session before the audio was sent")
        await socket.send({"type": "audio", "audio": base64.b64encode(frame).decode("ascii")})

    async def _wait_flushed(self, reader: asyncio.Task[None]) -> None:
        """Wait for the reader to see `flushed`, within the flush budget."""
        budget = self._timeouts.stt_flush
        try:
            async with asyncio.timeout(budget):
                await asyncio.wait((reader,))
        except TimeoutError as err:
            raise GradiumTimeoutError(
                f"Gradium ASR did not confirm the flush in time (flush, {budget} s)"
            ) from err
        reader.result()
        if not self._flushed.is_set():
            raise GradiumServerError("Gradium ASR ended the session before confirming the flush")

    def _append(self, text: Any) -> None:
        """Keep a non-empty transcript segment."""
        if isinstance(text, str) and text.strip():
            self._segments.append(text.strip())
