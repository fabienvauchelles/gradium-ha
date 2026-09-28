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
# Region-tagged variants accepted by the STT entity. Home Assistant checks the
# requested tag against the declared list as is, so "fr-FR" must be listed next
# to "fr"; every variant is sent to Gradium as its base code.
LANGUAGE_REGIONS: Final[dict[str, tuple[str, ...]]] = {
    "fr": ("FR", "BE", "CA", "CH", "LU"),
    "en": ("US", "GB", "AU", "CA", "IE", "IN", "NZ", "ZA"),
    "de": ("DE", "AT", "CH", "LU"),
    "es": ("ES", "MX", "AR", "CL", "CO", "US"),
    "pt": ("PT", "BR"),
}

# Gradium streams pcm_48000; Home Assistant converts it with ffmpeg for the satellite.
TTS_SAMPLE_RATE: Final = 48000
