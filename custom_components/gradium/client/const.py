"""Constants of the Gradium wire protocol as the integration uses it.

`REGION_ENDPOINTS` and `DEFAULT_TIMEOUTS` are read through this module at the
time a client is built, never bound as default argument values, so tests can
redirect the client to a fake server and shorten every time budget.
"""

from __future__ import annotations

from typing import Final

from .models import Endpoint, Region, Timeouts

REGION_ENDPOINTS: Final[dict[Region, Endpoint]] = {
    Region.EU: Endpoint(
        rest_base="https://eu.api.gradium.ai/api",
        ws_base="wss://eu.api.gradium.ai/api",
    ),
    Region.GLOBAL: Endpoint(
        rest_base="https://api.gradium.ai/api",
        ws_base="wss://api.gradium.ai/api",
    ),
}

DEFAULT_TIMEOUTS: Timeouts = Timeouts()

API_KEY_HEADER: Final = "x-api-key"

TTS_PATH: Final = "/speech/tts"
STT_PATH: Final = "/speech/asr"
VOICES_PATH: Final = "/voices/"
CREDITS_PATH: Final = "/usages/credits"

# The voice listing only returns the organisation's own voices unless the
# catalogue is asked for explicitly.
VOICES_PARAMS: Final[dict[str, str]] = {"include_catalog": "true", "limit": "1000"}

# STT input: 80 ms frames of 16 kHz signed 16-bit little-endian mono PCM.
STT_FRAME_BYTES: Final = 2560
STT_INPUT_FORMAT: Final = "pcm_16000"
FLUSH_ID: Final = 1

TTS_OUTPUT_FORMAT_PREFIX: Final = "pcm_"

# WebSocket close codes the service uses.
CLOSE_POLICY_VIOLATION: Final = 1008  # bad key, no subscription, no credit or refused request
CLOSE_PROTOCOL_ERROR: Final = 1002
CLOSE_INTERNAL_ERROR: Final = 1011
