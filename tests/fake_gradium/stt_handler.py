"""The fake ASR WebSocket session, played message by message.

Wire shape follows docs/protocol.md (STT sequence): `ready`
reports the model rate (24000) whatever the input format; every audio frame is
answered with a `step` VAD message; words of the fixed transcript arrive as
`text` plus `end_text`, one per frame from the third frame on, lagging the
audio. The last word is held until the client flushes, as the real server only
releases the tail of an utterance on `flush`, so a client that returns before
`flushed` loses it.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from aiohttp import web

from ..fixtures import STT_LEAD_IN_FRAMES, TRANSCRIPT_WORDS
from .behaviors import SttBehavior, SttRecord, send_error, send_policy_refusal

# The error comes on the third frame of the caller's audio, after the silent lead-in.
ERROR_AFTER_FRAMES = STT_LEAD_IN_FRAMES + 3
FIRST_WORD_FRAME = 3
FRAME_SECONDS = 0.08
VAD_HORIZONS = (0.5, 1.0, 2.0, 3.0)


class SttPlayer:
    """Answers the client messages of one ASR session."""

    def __init__(self, behavior: SttBehavior, record: SttRecord, release: asyncio.Event) -> None:
        self._behavior = behavior
        self._record = record
        self._release = release  # set when the server stops, ends a deliberate stall
        empty = behavior is SttBehavior.EMPTY_TRANSCRIPT
        self._words: list[str] = [] if empty else list(TRANSCRIPT_WORDS)
        self._next_word = 0

    async def on_message(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> bool:
        """Answer one client message; True once the server has ended the session."""
        kind = data.get("type")
        if kind == "setup":
            return await self._on_setup(ws, data)
        if kind == "audio":
            return await self._on_audio(ws, str(data.get("audio", "")))
        if kind == "flush":
            return await self._on_flush(ws, data.get("flush_id"))
        if kind == "end_of_stream":
            return await self._on_end(ws)
        return False

    async def _on_end(self, ws: web.WebSocketResponse) -> bool:
        if self._behavior is SttBehavior.IGNORES_CLOSE:
            # Stop reading: the client's close frame is never answered.
            await self._release.wait()
            return True
        await ws.send_json({"type": "end_of_stream"})
        await ws.close()
        return True

    async def _on_setup(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> bool:
        if self._behavior is SttBehavior.POLICY_REFUSED:
            await send_policy_refusal(ws, self._record)
            return True
        if self._behavior is SttBehavior.NEVER_READY:
            return False
        config = data.get("json_config") or {}
        ready = {
            "type": "ready",
            "model_name": data.get("model_name", "default"),
            "model_ext": "fake@1",
            "sample_rate": 24000,
            "frame_size": 1920,
            "delay_in_frames": config.get("delay_in_frames", 7),
        }
        await ws.send_json(ready)
        return False

    async def _on_audio(self, ws: web.WebSocketResponse, encoded: str) -> bool:
        self._record.frames.append(base64.b64decode(encoded))
        count = len(self._record.frames)
        if self._behavior is SttBehavior.ERROR_MID_STREAM and count == ERROR_AFTER_FRAMES:
            await send_error(ws, self._record)
            return True
        vad = [{"horizon_s": horizon, "inactivity_prob": 0.01} for horizon in VAD_HORIZONS]
        await ws.send_json(
            {"type": "step", "vad": vad, "total_duration_s": round(count * FRAME_SECONDS, 2)}
        )
        held_back = len(self._words) - 1
        if count >= FIRST_WORD_FRAME and self._next_word < held_back:
            await self._send_next_word(ws)
        return False

    async def _send_next_word(self, ws: web.WebSocketResponse) -> None:
        word = self._words[self._next_word]
        start = round(self._next_word * 0.3, 2)
        self._next_word += 1
        await ws.send_json({"type": "text", "text": word, "start_s": start})
        await ws.send_json({"type": "end_text", "stop_s": start + 0.3})

    async def _on_flush(self, ws: web.WebSocketResponse, flush_id: Any) -> bool:
        if self._behavior is SttBehavior.NEVER_FLUSHED:
            return False
        while self._next_word < len(self._words):
            await self._send_next_word(ws)
        await ws.send_json({"type": "flushed", "flush_id": flush_id})
        return False
