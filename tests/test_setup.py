"""Config entry lifecycle: setup against the fake server, failures, unload."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gradium.const import DOMAIN

from .conftest import assert_key_not_leaked, reauth_flows
from .fake_gradium import FakeGradiumServer, RestFailure
from .fixtures import API_KEY, WRONG_API_KEY

ENTITY_IDS = ("stt.gradium", "tts.gradium")


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_both_entities_on_one_service_device(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Setup lists the voices once with the key, then exposes STT and TTS on one device."""
    await _set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    voices_calls = [call for call in fake_gradium.rest_requests if call.path == "/api/voices/"]
    assert len(voices_calls) == 1
    assert voices_calls[0].authorized
    assert voices_calls[0].query.get("include_catalog") == "true"

    entities = er.async_get(hass)
    device_ids = set()
    for entity_id in ENTITY_IDS:
        assert hass.states.get(entity_id) is not None, entity_id
        entry = entities.async_get(entity_id)
        assert entry is not None
        assert entry.config_entry_id == config_entry.entry_id
        device_ids.add(entry.device_id)
    assert len(device_ids) == 1

    device = dr.async_get(hass).async_get(device_ids.pop() or "")
    assert isinstance(device, dr.DeviceEntry)
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert (DOMAIN, config_entry.entry_id) in device.identifiers
    assert fake_gradium.tts_sessions == []
    assert fake_gradium.stt_sessions == []
    assert_key_not_leaked(caplog)


async def test_rejected_key_fails_setup_and_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 401 on the voices list is an auth failure, not a retry, and asks for a new key."""
    fake_gradium.valid_key = WRONG_API_KEY

    await _set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(reauth_flows(hass)) == 1
    for entity_id in ENTITY_IDS:
        assert hass.states.get(entity_id) is None
    assert_key_not_leaked(caplog)


async def test_server_error_retries_setup_later(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 500 is transient: setup is retried and no reauth is asked for."""
    fake_gradium.rest_failure = RestFailure.SERVER_ERROR

    await _set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert reauth_flows(hass) == []
    assert_key_not_leaked(caplog)


async def test_unreachable_server_retries_setup_later(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
) -> None:
    """A refused connection maps to a retry as well."""
    await fake_gradium.stop()

    await _set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert reauth_flows(hass) == []


async def test_unload_leaves_no_entity_available(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
) -> None:
    """Unloading the entry takes both entities down and keeps the key in the entry."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    for entity_id in ENTITY_IDS:
        state = hass.states.get(entity_id)
        assert state is None or state.state == STATE_UNAVAILABLE, entity_id
    assert setup_integration.data["api_key"] == API_KEY


async def test_reload_lists_the_voices_again(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
) -> None:
    """A reload builds a new client and refreshes the cached voices."""
    assert await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.LOADED
    voices_calls = [call for call in fake_gradium.rest_requests if call.path == "/api/voices/"]
    assert len(voices_calls) == 2
    for entity_id in ENTITY_IDS:
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state != STATE_UNAVAILABLE
