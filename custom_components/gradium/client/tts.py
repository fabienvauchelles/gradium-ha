"""One streaming text-to-speech session over the Gradium TTS WebSocket.

Text is sent by a sender task while audio is read, because Gradium starts
synthesizing on partial text: the first audio arrives before the last text
message is sent. The socket opens when the caller first pulls audio and closes
however the generator ends (normal end, error, `aclose()` or cancellation).
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import AsyncGenerator, AsyncIterable
from typing import Any

import aiohttp

from .const import TTS_OUTPUT_FORMAT_PREFIX, TTS_PATH
from .errors import GradiumServerError, GradiumTimeoutError
from .models import Endpoint, Timeouts, TtsSettings
from .socket import GradiumSocket
from .tasks import stop_task
from .text_chunker import WordChunker


class GradiumTtsSession:
    """Drive one TTS WebSocket from setup to the server's end_of_stream."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        endpoint: Endpoint,
        timeouts: Timeouts,
        settings: TtsSettings,
    ) -> None:
        """Store what the session needs; nothing is opened yet."""
        self._session = session
        self._api_key = api_key
        self._url = f"{endpoint.ws_base}{TTS_PATH}"
        self._timeouts = timeouts
        self._settings = settings
        self._receiver: asyncio.Task[dict[str, Any]] | None = None

    async def stream(self, text: AsyncIterable[str]) -> AsyncGenerator[bytes]:
        """Yield raw PCM s16le mono chunks as the server produces them."""
        socket = await GradiumSocket.connect(
            self._session, self._url, self._api_key, self._timeouts
        )
        sender: asyncio.Task[None] | None = None
        try:
            await self._setup(socket)
            sender = asyncio.create_task(self._send_text(socket, text), name="gradium-tts-sender")
            while True:
                message = await self._next_message(socket, sender)
                kind = message.get("type")
                if kind == "end_of_stream":
                    return
                if kind == "audio":
                    yield _decode_audio(message)
        finally:
            await stop_task(sender)
            await stop_task(self._receiver)
            await socket.close()

    async def _setup(self, socket: GradiumSocket) -> None:
        """Send the setup message and check the ready answer."""
        rate = self._settings.sample_rate
        await socket.send(
            {
                "type": "setup",
                "model_name": self._settings.model_name,
                "voice_id": self._settings.voice_id,
                "output_format": f"{TTS_OUTPUT_FORMAT_PREFIX}{rate}",
            }
        )
        ready = await socket.receive(self._timeouts.ready, phase="ready")
        if ready.get("type") != "ready":
            raise GradiumServerError(
                f"Gradium TTS answered the setup with {ready.get('type')!r} instead of ready"
            )
        if ready.get("sample_rate") != rate:
            raise GradiumServerError(
                f"Gradium TTS announced a sample rate of {ready.get('sample_rate')!r}, "
                f"{rate} was requested"
            )

    async def _send_text(self, socket: GradiumSocket, text: AsyncIterable[str]) -> None:
        """Send the text as whole words, then end_of_stream."""
        chunker = WordChunker()
        async for delta in text:
            words = chunker.push(delta)
            if words:
                await socket.send({"type": "text", "text": words})
        rest = chunker.flush()
        if rest:
            await socket.send({"type": "text", "text": rest})
        await socket.send({"type": "end_of_stream"})

    async def _next_message(
        self, socket: GradiumSocket, sender: asyncio.Task[None]
    ) -> dict[str, Any]:
        """Receive the next message, racing the sender until it has finished.

        While text is still being sent there is no time limit: the text source
        (an LLM) sets the pace, and a sender failure is re-raised unchanged.
        Once end_of_stream is sent, each message must come within tts_idle.
        One receive task is kept across calls so no message is ever dropped.
        """
        receiver = self._receiver or asyncio.create_task(
            socket.receive(None), name="gradium-tts-receiver"
        )
        self._receiver = receiver
        if not sender.done():
            await asyncio.wait((receiver, sender), return_when=asyncio.FIRST_COMPLETED)
        if not receiver.done():
            sender.result()
            await self._wait_idle(receiver)
        self._receiver = None
        return receiver.result()

    async def _wait_idle(self, receiver: asyncio.Task[dict[str, Any]]) -> None:
        """Wait for the pending receive within the idle budget."""
        budget = self._timeouts.tts_idle
        try:
            async with asyncio.timeout(budget):
                await receiver
        except TimeoutError as err:
            raise GradiumTimeoutError(
                f"Gradium TTS stopped sending audio (tts idle, {budget} s)"
            ) from err


def _decode_audio(message: dict[str, Any]) -> bytes:
    """Decode the base64 PCM payload of an audio message."""
    payload = message.get("audio")
    if not isinstance(payload, str):
        raise GradiumServerError("Gradium TTS sent an audio message without audio")
    try:
        return base64.b64decode(payload, validate=True)
    except binascii.Error as err:
        raise GradiumServerError("Gradium TTS sent audio that is not valid base64") from err
