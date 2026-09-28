"""Config flow, reauthentication and options flow, from the first form to the next TTS call."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult, FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gradium.const import (
    CONF_LANGUAGE,
    CONF_REGION,
    CONF_TTS_MODEL,
    CONF_VOICE,
    DOMAIN,
    TITLE,
)

from .conftest import DEFAULT_OPTIONS, assert_key_not_leaked, speak
from .fake_gradium import FakeGradiumServer, RestFailure
from .fixtures import (
    API_KEY,
    CLAIRE,
    FAMILY,
    FRENCH_CATALOG,
    NEW_API_KEY,
    SENTENCE,
    WRONG_API_KEY,
)

CREDITS_PATH = "/api/usages/credits"
BETA_MODEL = "gradium-tts-beta"


def _select_values(result: FlowResult[Any, Any], field: str) -> list[str]:
    """Values offered by one select field of a form."""
    schema = result["data_schema"]
    assert schema is not None
    for key, validator in schema.schema.items():
        if str(key) == field:
            options = validator.config["options"]
            return [option["value"] if isinstance(option, dict) else option for option in options]
    raise AssertionError(f"the form has no {field} field")


async def _start_user_flow(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert not result["errors"]
    assert _select_values(result, CONF_REGION) == ["eu", "global"]
    return result["flow_id"]


@pytest.mark.parametrize("region", ["eu", "global"])
async def test_user_flow_creates_the_entry_with_default_options(
    hass: HomeAssistant,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
    region: str,
) -> None:
    """A working key is checked with a credits read, then saved and set up."""
    flow_id = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: API_KEY, CONF_REGION: region}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TITLE
    assert result["data"] == {CONF_API_KEY: API_KEY, CONF_REGION: region}
    assert result["options"] == DEFAULT_OPTIONS
    credits_calls = [call for call in fake_gradium.rest_requests if call.path == CREDITS_PATH]
    assert len(credits_calls) == 1
    assert credits_calls[0].authorized
    assert result["result"].state is ConfigEntryState.LOADED
    assert hass.states.get("tts.gradium") is not None
    assert_key_not_leaked(caplog)


async def test_rejected_key_shows_invalid_auth_then_a_good_key_succeeds(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """A 401 keeps the form open with invalid_auth; the retry goes through."""
    flow_id = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: WRONG_API_KEY, CONF_REGION: "eu"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: API_KEY, CONF_REGION: "eu"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_API_KEY] == API_KEY
    assert_key_not_leaked(caplog)


async def test_server_error_shows_cannot_connect(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """A 500 is not the user's fault: cannot_connect, and nothing is saved."""
    fake_gradium.rest_failure = RestFailure.SERVER_ERROR
    flow_id = await _start_user_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: API_KEY, CONF_REGION: "eu"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert_key_not_leaked(caplog)


@pytest.mark.usefixtures("setup_integration")
async def test_second_entry_is_refused(hass: HomeAssistant) -> None:
    """One Gradium account per Home Assistant: a second flow aborts at once."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reauth_saves_the_new_key_and_reloads(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The key is rotated on Gradium's side; reauth stores it and speech works again."""
    fake_gradium.valid_key = NEW_API_KEY
    result = await setup_integration.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: NEW_API_KEY}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert setup_integration.data[CONF_API_KEY] == NEW_API_KEY
    assert setup_integration.data[CONF_REGION] == "eu"
    assert setup_integration.state is ConfigEntryState.LOADED
    await speak(hass, SENTENCE)
    assert fake_gradium.tts_sessions[-1].authorized
    assert_key_not_leaked(caplog)


async def test_reauth_with_a_rejected_key_shows_invalid_auth(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A wrong key in reauth keeps the form open and leaves the stored key alone."""
    fake_gradium.valid_key = NEW_API_KEY
    result = await setup_integration.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: WRONG_API_KEY}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert setup_integration.data[CONF_API_KEY] == API_KEY
    assert_key_not_leaked(caplog)


async def test_options_offer_french_and_custom_voices_and_reach_the_next_call(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_gradium: FakeGradiumServer
) -> None:
    """French catalogue voices plus custom ones; the saved choice drives the next TTS setup."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert set(_select_values(result, CONF_VOICE)) == {*FRENCH_CATALOG, FAMILY}
    assert BETA_MODEL in _select_values(result, CONF_TTS_MODEL)
    assert "fr" in _select_values(result, CONF_LANGUAGE)
    requests_before = len(fake_gradium.rest_requests)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_VOICE: CLAIRE, CONF_TTS_MODEL: BETA_MODEL, CONF_LANGUAGE: "fr"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(setup_integration.options) == {
        CONF_VOICE: CLAIRE,
        CONF_TTS_MODEL: BETA_MODEL,
        CONF_LANGUAGE: "fr",
    }
    # Saving reloads the entry, which lists the voices again; the flow itself calls nothing.
    assert len(fake_gradium.rest_requests) == requests_before + 1
    await speak(hass, SENTENCE)
    setup = fake_gradium.tts_sessions[-1].setup
    assert setup["voice_id"] == CLAIRE
    assert setup["model_name"] == BETA_MODEL


async def test_options_abort_while_the_entry_is_not_loaded(
    hass: HomeAssistant, config_entry: MockConfigEntry, fake_gradium: FakeGradiumServer
) -> None:
    """Without a loaded entry there are no voices to offer: the options flow aborts."""
    fake_gradium.rest_failure = RestFailure.SERVER_ERROR
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"
