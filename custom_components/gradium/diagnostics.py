"""Diagnostics for the Gradium integration, with the API key redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from .const import CONF_REGION
from .data import GradiumConfigEntry

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GradiumConfigEntry
) -> dict[str, Any]:
    """Return the entry settings and the cached voice counts. No call reaches Gradium."""
    voices_cached: int | None = None
    custom_voices: int | None = None
    if entry.state is ConfigEntryState.LOADED:
        voices = entry.runtime_data.voices
        voices_cached = len(voices)
        custom_voices = sum(1 for voice in voices if not voice.is_catalog)

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "region": entry.data.get(CONF_REGION),
        "voices_cached": voices_cached,
        "custom_voices": custom_voices,
    }
