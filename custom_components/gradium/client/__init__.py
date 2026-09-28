"""Gradium speech client: REST reads, streaming TTS and streaming STT.

This package never imports Home Assistant; the integration's adapters depend
on it, not the other way round.
"""

from __future__ import annotations

from .client import GradiumClient
from .errors import (
    GradiumAuthError,
    GradiumConnectionError,
    GradiumCreditsExhaustedError,
    GradiumError,
    GradiumServerError,
    GradiumTimeoutError,
)
from .models import Credits, Endpoint, Region, SttSettings, Timeouts, TtsSettings, Voice
from .pcm import PcmFramer, wav_header

__all__ = [
    "Credits",
    "Endpoint",
    "GradiumAuthError",
    "GradiumClient",
    "GradiumConnectionError",
    "GradiumCreditsExhaustedError",
    "GradiumError",
    "GradiumServerError",
    "GradiumTimeoutError",
    "PcmFramer",
    "Region",
    "SttSettings",
    "Timeouts",
    "TtsSettings",
    "Voice",
    "wav_header",
]
