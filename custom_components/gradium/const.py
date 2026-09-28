"""Constants of the Home Assistant layer of the Gradium integration."""

from __future__ import annotations

from typing import Final

from .client import Region

DOMAIN: Final = "gradium"
TITLE: Final = "Gradium"
MANUFACTURER: Final = "Gradium"
CONFIGURATION_URL: Final = "https://gradium.ai"

CONF_REGION: Final = "region"
CONF_VOICE: Final = "voice"
CONF_TTS_MODEL: Final = "tts_model"
CONF_LANGUAGE: Final = "language"

# Per-call TTS option, next to tts.ATTR_VOICE. Same value as homeassistant.const.ATTR_MODEL.
ATTR_MODEL: Final = "model"

DEFAULT_REGION: Final = Region.EU
# Gaspard, a French catalog voice. Claire ("zIGaffB0kKEBG_8u") is the female alternative.
DEFAULT_VOICE: Final = "iEu63s1rhn_kegTr"
DEFAULT_TTS_MODEL: Final = "default"
TTS_MODELS: Final = ("default", "gradium-tts-beta")
DEFAULT_LANGUAGE: Final = "fr"
SUPPORTED_LANGUAGES: Final = ("fr", "en", "de", "es", "pt")

# Gradium streams pcm_48000; Home Assistant converts it with ffmpeg for the satellite.
TTS_SAMPLE_RATE: Final = 48000
