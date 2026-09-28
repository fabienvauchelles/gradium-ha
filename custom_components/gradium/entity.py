"""Shared entity base: one service device per config entry."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import CONFIGURATION_URL, DOMAIN, MANUFACTURER, TITLE
from .data import GradiumConfigEntry


class GradiumEntity(Entity):
    """Base of the STT and TTS entities, attached to the Gradium service device.

    The entity carries its own name rather than borrowing the device name
    (`has_entity_name` with `name = None`): the TTS manager refuses to generate
    audio for an engine whose `name` is None ("TTS engine name is not set."),
    and naming it "Gradium" keeps the entity ids `tts.gradium` and `stt.gradium`.
    """

    _attr_has_entity_name = False
    _attr_name = TITLE
    _attr_should_poll = False

    def __init__(self, entry: GradiumConfigEntry, kind: str) -> None:
        """Bind the entity to its config entry; `kind` tells STT and TTS apart."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=TITLE,
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=CONFIGURATION_URL,
        )
