"""Made-up constants and payload builders shared by the fake server and the tests.

Nothing here is a real credential or real account data. The voice uids of the
three French catalogue voices match the ones the integration ships as defaults,
so the options flow sees the ids it expects.
"""

from __future__ import annotations

import struct
from typing import Any

API_KEY = "test-key-not-a-real-secret"
NEW_API_KEY = "test-key-rotated-not-a-real-secret"
WRONG_API_KEY = "test-key-wrong-not-a-real-secret"

GASPARD = "iEu63s1rhn_kegTr"
CLAIRE = "zIGaffB0kKEBG_8u"
APOLLINE = "6oIkS98REoVZ1dEw"
MAXIMILIAN = "0y1VZjPabOBU3rWy"
EMMA = "enCatalogVoice01"
FAMILY = "customVoice00001"

FRENCH_CATALOG = (APOLLINE, CLAIRE, GASPARD)

TTS_SAMPLES_PER_CHUNK = 3840  # 80 ms at 48 kHz, as the real server sends
STT_FRAME_BYTES = 2560  # 80 ms at 16 kHz s16le
STT_LEAD_IN_FRAMES = 4  # 320 ms of silence the client sends before the caller's audio
HA_CHUNK_BYTES = 320  # 10 ms at 16 kHz s16le, what the assist pipeline forwards

TRANSCRIPT = "Allume la lumière du canapé."
TRANSCRIPT_WORDS = tuple(TRANSCRIPT.split())

SENTENCE = "D'accord, j'ai allumé la lumière du canapé."


def _voice(
    uid: str, name: str, language: str | None, gender: str | None, catalog: bool
) -> dict[str, Any]:
    """One entry of GET /voices/, with the fields the real API returns."""
    return {
        "translations": {},
        "gender": gender,
        "age": None,
        "locale": None,
        "uid": uid,
        "name": name,
        "description": f"Made-up description of {name}.",
        "filename": None if catalog else "recording.webm",
        "start_s": None if catalog else 0.0,
        "is_catalog": catalog,
        "is_pro_clone": False,
        "language": language,
        "tags": [],
    }


def voices_payload() -> list[dict[str, Any]]:
    """Three French catalogue voices, one German, one English, one custom English voice."""
    return [
        _voice(MAXIMILIAN, "Maximilian", "de", "Male", catalog=True),
        _voice(GASPARD, "Gaspard", "fr", "Male", catalog=True),
        _voice(EMMA, "Emma", "en", "Female", catalog=True),
        _voice(CLAIRE, "Claire", "fr", "Female", catalog=True),
        _voice(FAMILY, "Family", "en", None, catalog=False),
        _voice(APOLLINE, "Apolline", "fr", "Female", catalog=True),
    ]


REMAINING_CREDITS = 123456


def credits_payload(remaining: int = REMAINING_CREDITS) -> dict[str, Any]:
    """GET /usages/credits response with made-up values."""
    return {
        "remaining_credits": remaining,
        "allocated_credits": 500000,
        "billing_period": "01-2026",
        "next_rollover_date": None,
        "plan_name": "",
    }


def _ramp(count: int, offset: int) -> bytes:
    """Little-endian int16 ramp, distinct per offset so chunks can be told apart."""
    values = [((offset * 131 + index) % 4000) - 2000 for index in range(count)]
    return struct.pack(f"<{count}h", *values)


def tts_audio_chunk(index: int) -> bytes:
    """The PCM the fake TTS sends as its index-th audio message."""
    return _ramp(TTS_SAMPLES_PER_CHUNK, index + 1)


def speech_pcm(duration_ms: int) -> bytes:
    """Deterministic 16 kHz mono s16le audio of the given length."""
    return _ramp(16 * duration_ms, 7)


def ha_chunks(pcm: bytes) -> list[bytes]:
    """Split audio the way the assist pipeline forwards it: 10 ms chunks."""
    return [pcm[start : start + HA_CHUNK_BYTES] for start in range(0, len(pcm), HA_CHUNK_BYTES)]
