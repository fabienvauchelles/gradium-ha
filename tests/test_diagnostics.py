"""Diagnostics download: useful for support, and never the API key."""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.gradium.const import CONF_REGION

from .conftest import DEFAULT_OPTIONS, assert_key_not_leaked
from .fake_gradium import FakeGradiumServer
from .fixtures import API_KEY, voices_payload

REDACTED = "**REDACTED**"


async def test_diagnostics_redact_the_key_and_describe_the_setup(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Downloaded through the HTTP API, as a user would; no live Gradium call is made."""
    requests_before = len(fake_gradium.rest_requests)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)

    entry = diagnostics["entry"]
    assert isinstance(entry, dict)
    assert entry["data"] == {"api_key": REDACTED, CONF_REGION: "eu"}
    assert entry["options"] == DEFAULT_OPTIONS
    assert diagnostics["region"] == "eu"
    assert diagnostics["voices_cached"] == len(voices_payload())
    assert diagnostics["custom_voices"] == 1
    serialized = json.dumps(diagnostics)
    assert API_KEY not in serialized
    assert len(fake_gradium.rest_requests) == requests_before
    assert fake_gradium.tts_sessions == []
    assert_key_not_leaked(caplog, serialized)
