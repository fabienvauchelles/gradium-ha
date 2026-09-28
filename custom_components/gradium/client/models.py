"""Value objects exchanged between the Gradium client and its callers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Region(StrEnum):
    """Gradium API region the requests are routed to."""

    EU = "eu"
    GLOBAL = "global"


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Base URLs of one Gradium region, both without a trailing slash."""

    rest_base: str
    ws_base: str


@dataclass(frozen=True, slots=True)
class Voice:
    """A voice the account can synthesize with."""

    uid: str
    name: str
    language: str | None
    gender: str | None
    description: str | None
    is_catalog: bool  # False for the organisation's own (custom) voices


@dataclass(frozen=True, slots=True)
class Credits:
    """Credit balance of the account for the current billing period."""

    remaining: int
    allocated: int
    billing_period: str | None
    plan_name: str | None


@dataclass(frozen=True, slots=True)
class TtsSettings:
    """Parameters of one text-to-speech session."""

    voice_id: str
    model_name: str = "default"
    sample_rate: int = 48000  # sent as output_format f"pcm_{sample_rate}"


@dataclass(frozen=True, slots=True)
class SttSettings:
    """Parameters of one speech-to-text session."""

    language: str = "fr"
    model_name: str = "default"
    delay_in_frames: int = 7


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Time budgets, in seconds, of the phases of a Gradium exchange."""

    connect: float = 10.0  # WebSocket handshake, and the total of a REST call
    ready: float = 5.0  # setup sent until ready received
    tts_idle: float = 10.0  # max server silence once the TTS end_of_stream was sent
    stt_flush: float = 3.0  # flush sent until flushed received
    close: float = 2.0  # wait for the server's close frame before dropping the socket
