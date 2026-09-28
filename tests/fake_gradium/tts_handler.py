"""The fake TTS WebSocket session, played message by message.

Wire shape follows docs/protocol.md (TTS sequence): `ready`
carries the sample rate of the requested `pcm_<rate>` output format; every
`text` message is answered with one base64 audio chunk of 3840 samples and a
word-level `text` alignment message per word; the client's `end_of_stream` is
answered with `end_of_stream`, then the server closes.
"""

from __future__ import annotations

import base64
from typing import Any

from aiohttp import web

from ..fixtures import TTS_SAMPLES_PER_CHUNK, tts_audio_chunk
from .behaviors import TtsBehavior, TtsRecord, send_error, send_policy_refusal

CHUNK_SECONDS = 0.08
DEFAULT_RATE = 48000


def _sample_rate(output_format: str) -> int:
    """`pcm_16000` gives 16000; plain `pcm` or anything else gives 48 kHz."""
    rate = output_format.removeprefix("pcm_")
    return int(rate) if rate.isdigit() else DEFAULT_RATE


class TtsPlayer:
    """Answers the client messages of one TTS session."""

    def __init__(self, behavior: TtsBehavior, record: TtsRecord) -> None:
        self._behavior = behavior
        self._record = record
        self._words_spoken = 0

    async def on_message(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> bool:
        """Answer one client message; True once the server has ended the session."""
        kind = data.get("type")
        if kind == "setup":
            return await self._on_setup(ws, data)
        if kind == "text":
            return await self._on_text(ws, str(data.get("text", "")))
        if kind == "end_of_stream":
            return await self._on_end(ws)
        return False

    async def _on_setup(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> bool:
        if self._behavior is TtsBehavior.POLICY_REFUSED:
            await send_policy_refusal(ws, self._record)
            return True
        if self._behavior is TtsBehavior.NEVER_READY:
            return False
        ready = {
            "type": "ready",
            "model_name": data.get("model_name", "default"),
            "model_ext": "fake@1",
            "sample_rate": _sample_rate(str(data.get("output_format", "pcm"))),
            "frame_size": TTS_SAMPLES_PER_CHUNK,
            "audio_stream_names": ["audio"],
            "text_stream_names": ["text"],
        }
        await ws.send_json(ready)
        return False

    async def _on_text(self, ws: web.WebSocketResponse, text: str) -> bool:
        index = len(self._record.audio_sent)
        chunk = tts_audio_chunk(index)
        self._record.audio_sent.append(chunk)
        await ws.send_json(
            {
                "type": "audio",
                "audio": base64.b64encode(chunk).decode(),
                "start_s": round(index * CHUNK_SECONDS, 2),
                "stop_s": round((index + 1) * CHUNK_SECONDS, 2),
                "audio_tokens": [],
                "stream_id": 0,
                "client_req_id": None,
            }
        )
        if self._behavior is TtsBehavior.ERROR_AFTER_FIRST_AUDIO:
            await send_error(ws, self._record)
            return True
        for word in text.split():
            await self._send_alignment(ws, word)
        return False

    async def _send_alignment(self, ws: web.WebSocketResponse, word: str) -> None:
        start = round(self._words_spoken * 0.3, 2)
        self._words_spoken += 1
        await ws.send_json({"type": "text", "text": word, "start_s": start, "stop_s": start + 0.3})

    async def _on_end(self, ws: web.WebSocketResponse) -> bool:
        if self._behavior is TtsBehavior.SILENT_AFTER_EOS:
            return False
        await ws.send_json({"type": "end_of_stream"})
        await ws.close()
        return True
