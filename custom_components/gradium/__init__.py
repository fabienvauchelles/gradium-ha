"""The Gradium integration: speech-to-text and streaming text-to-speech."""

from __future__ import annotations

from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import (
    GradiumAuthError,
    GradiumClient,
    GradiumConnectionError,
    GradiumServerError,
    GradiumTimeoutError,
    Region,
)
from .const import CONF_REGION
from .data import GradiumConfigEntry, GradiumRuntimeData

PLATFORMS: list[Platform] = [Platform.STT, Platform.TTS]


async def async_setup_entry(hass: HomeAssistant, entry: GradiumConfigEntry) -> bool:
    """Set up Gradium from a config entry.

    The voice list is read once here: it feeds the options flow and the TTS
    voice picker, and the call doubles as a check that the stored key still works.
    Options changes reload the entry through `OptionsFlowWithReload`.
    """
    client = GradiumClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        Region(entry.data[CONF_REGION]),
    )
    try:
        voices = await client.async_list_voices()
    except GradiumAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except (GradiumConnectionError, GradiumTimeoutError, GradiumServerError) as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = GradiumRuntimeData(client=client, voices=voices)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GradiumConfigEntry) -> bool:
    """Unload a config entry. The shared aiohttp session is Home Assistant's and stays open."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
