"""Streaming text-to-speech entity backed by the Gradium TTS WebSocket."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import override

from homeassistant.components.tts import (
    ATTR_VOICE,
    TextToSpeechEntity,
    TTSAudioRequest,
    TTSAudioResponse,
)
from homeassistant.components.tts import Voice as TtsVoice
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import GradiumError, TtsSettings, wav_header
from .const import (
    ATTR_MODEL,
    CONF_LANGUAGE,
    CONF_TTS_MODEL,
    CONF_VOICE,
    DEFAULT_LANGUAGE,
    DEFAULT_TTS_MODEL,
    DEFAULT_VOICE,
    SUPPORTED_LANGUAGES,
    TTS_SAMPLE_RATE,
)
from .data import GradiumConfigEntry, voices_for_language
from .entity import GradiumEntity
from .errors import log_gradium_error, raise_for_gradium_error

_WAV_EXTENSION = "wav"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GradiumConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Gradium TTS entity."""
    async_add_entities([GradiumTtsEntity(entry)])


class GradiumTtsEntity(GradiumEntity, TextToSpeechEntity):
    """Text-to-speech that sends whole words as they arrive and streams audio back.

    Only `async_stream_tts_audio` is implemented: overriding it makes Home
    Assistant route both plain strings and streamed messages through it. The
    `preferred_*` options are deliberately not supported, so Home Assistant pops
    them and converts the 48 kHz WAV for the satellite with ffmpeg itself.
    """

    def __init__(self, entry: GradiumConfigEntry) -> None:
        """Read the defaults from the entry options; an options change reloads the entry."""
        super().__init__(entry, "tts")
        self._attr_supported_languages = list(SUPPORTED_LANGUAGES)
        self._attr_supported_options = [ATTR_VOICE, ATTR_MODEL]
        self._default_voice: str = entry.options.get(CONF_VOICE, DEFAULT_VOICE)
        self._default_model: str = entry.options.get(CONF_TTS_MODEL, DEFAULT_TTS_MODEL)
        self._attr_default_language = entry.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)
        self._attr_default_options = {
            ATTR_VOICE: self._default_voice,
            ATTR_MODEL: self._default_model,
        }

    @callback
    @override
    def async_get_supported_voices(self, language: str) -> list[TtsVoice]:
        """Return the catalog voices of `language` plus the custom voices, sorted by name."""
        voices = voices_for_language(self._entry.runtime_data.voices, language)
        return [TtsVoice(voice.uid, voice.name) for voice in voices]

    @override
    async def async_stream_tts_audio(self, request: TTSAudioRequest) -> TTSAudioResponse:
        """Return a lazy WAV stream: the socket opens when Home Assistant first pulls audio."""
        settings = TtsSettings(
            voice_id=request.options.get(ATTR_VOICE, self._default_voice),
            model_name=request.options.get(ATTR_MODEL, self._default_model),
            sample_rate=TTS_SAMPLE_RATE,
        )
        return TTSAudioResponse(
            extension=_WAV_EXTENSION,
            data_gen=self._data_gen(request.message_gen, settings),
        )

    async def _data_gen(
        self, message_gen: AsyncGenerator[str], settings: TtsSettings
    ) -> AsyncGenerator[bytes]:
        """Yield a streaming WAV header, then the PCM chunks as Gradium sends them.

        `aclosing` makes closing this generator close the client generator right
        away, which closes the socket instead of leaving it to garbage collection.
        """
        yield wav_header(TTS_SAMPLE_RATE)
        client = self._entry.runtime_data.client
        try:
            async with aclosing(client.synthesize(message_gen, settings)) as audio:
                async for chunk in audio:
                    yield chunk
        except GradiumError as err:
            log_gradium_error(err, "synthesize speech")
            raise_for_gradium_error(self.hass, self._entry, err)
