"""Config flow for the Gradium integration: API key, region and reauthentication."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .client import (
    GradiumAuthError,
    GradiumClient,
    GradiumConnectionError,
    GradiumServerError,
    GradiumTimeoutError,
    Region,
)
from .const import (
    CONF_LANGUAGE,
    CONF_REGION,
    CONF_TTS_MODEL,
    CONF_VOICE,
    DEFAULT_LANGUAGE,
    DEFAULT_REGION,
    DEFAULT_TTS_MODEL,
    DEFAULT_VOICE,
    DOMAIN,
    TITLE,
)
from .options_flow import GradiumOptionsFlow

_LOGGER = logging.getLogger(__name__)

_API_KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): _API_KEY_SELECTOR,
        vol.Required(CONF_REGION, default=DEFAULT_REGION.value): SelectSelector(
            SelectSelectorConfig(
                options=[region.value for region in Region],
                translation_key=CONF_REGION,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)

STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_API_KEY): _API_KEY_SELECTOR})


async def _async_validate(hass: HomeAssistant, api_key: str, region: Region) -> str | None:
    """Check the key with a credits read.

    Returns the `config.error` key to show, or None when the key works.
    """
    client = GradiumClient(async_get_clientsession(hass), api_key, region)
    try:
        await client.async_get_credits()
    except GradiumAuthError as err:
        _LOGGER.debug("Gradium refused the API key: %s", err)
        return "invalid_auth"
    except (GradiumConnectionError, GradiumTimeoutError, GradiumServerError) as err:
        _LOGGER.warning("Could not check the Gradium API key: %s", err)
        return "cannot_connect"
    return None


class GradiumConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the Gradium API key and region, and check them before saving.

    A single entry is allowed: the manifest sets `single_config_entry`, so Home
    Assistant aborts a second flow with `single_instance_allowed` by itself.
    """

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect the API key and the region."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            region = Region(user_input[CONF_REGION])
            error = await _async_validate(self.hass, api_key, region)
            if error is None:
                return self.async_create_entry(
                    title=TITLE,
                    data={CONF_API_KEY: api_key, CONF_REGION: region.value},
                    options={
                        CONF_VOICE: DEFAULT_VOICE,
                        CONF_TTS_MODEL: DEFAULT_TTS_MODEL,
                        CONF_LANGUAGE: DEFAULT_LANGUAGE,
                    },
                )
            errors["base"] = error

        suggested = {CONF_REGION: user_input[CONF_REGION]} if user_input else {}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start again when Gradium refuses the stored key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new key, checked against the region already configured."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            api_key = user_input[CONF_API_KEY].strip()
            error = await _async_validate(self.hass, api_key, Region(entry.data[CONF_REGION]))
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=STEP_REAUTH_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GradiumOptionsFlow:
        """Return the options flow: voice, TTS model and language."""
        return GradiumOptionsFlow()
