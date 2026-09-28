"""Options flow for the Gradium integration: default voice, TTS model and language."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .client import Voice
from .const import (
    CONF_LANGUAGE,
    CONF_TTS_MODEL,
    CONF_VOICE,
    DEFAULT_LANGUAGE,
    DEFAULT_TTS_MODEL,
    DEFAULT_VOICE,
    SUPPORTED_LANGUAGES,
    TTS_MODELS,
)
from .data import GradiumConfigEntry, voices_for_language


def _voice_label(voice: Voice) -> str:
    """Name the voice, with its gender when Gradium gives one."""
    return f"{voice.name} ({voice.gender})" if voice.gender else voice.name


def _voice_options(voices: list[Voice], language: str, current: str) -> list[SelectOptionDict]:
    """Voices of the saved language plus custom voices, keeping the current voice listed."""
    offered = voices_for_language(voices, language)
    if all(voice.uid != current for voice in offered):
        known = [voice for voice in voices if voice.uid == current]
        offered = sorted([*offered, *known], key=lambda voice: voice.name.casefold())
    options = [SelectOptionDict(value=voice.uid, label=_voice_label(voice)) for voice in offered]
    if all(option["value"] != current for option in options):
        # The saved voice is no longer in the account's list: keep it selectable by uid.
        options.append(SelectOptionDict(value=current, label=current))
    return options


def _select(options: list[SelectOptionDict] | list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN, sort=False)
    )


class GradiumOptionsFlow(OptionsFlowWithReload):
    """Pick the default voice, model and language; saving reloads the entry.

    The voice list comes from the one read at setup, so the flow makes no call
    to Gradium and needs the entry to be loaded.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show or save the options."""
        entry: GradiumConfigEntry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        language = entry.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        voice = entry.options.get(CONF_VOICE, DEFAULT_VOICE)
        model = entry.options.get(CONF_TTS_MODEL, DEFAULT_TTS_MODEL)
        schema = vol.Schema(
            {
                vol.Required(CONF_VOICE, default=voice): _select(
                    _voice_options(entry.runtime_data.voices, language, voice)
                ),
                vol.Required(CONF_TTS_MODEL, default=model): _select(list(TTS_MODELS)),
                vol.Required(CONF_LANGUAGE, default=language): _select(list(SUPPORTED_LANGUAGES)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
