"""Speech-to-text entity backed by the Gradium ASR WebSocket."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from typing import override

from homeassistant.components.stt import (
    AudioBitRates,
    AudioChannels,
    AudioCodecs,
    AudioFormats,
    AudioSampleRates,
    SpeechMetadata,
    SpeechResult,
    SpeechResultState,
    SpeechToTextEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .client import GradiumAuthError, GradiumError, SttSettings
from .const import CONF_LANGUAGE, DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES
from .data import GradiumConfigEntry, base_language
from .entity import GradiumEntity
from .errors import log_gradium_error

_LOGGER = logging.getLogger(__name__)

_ACTION = "transcribe speech"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GradiumConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the Gradium STT entity."""
    async_add_entities([GradiumSttEntity(entry)])


class GradiumSttEntity(GradiumEntity, SpeechToTextEntity):
    """Speech-to-text that forwards 16 kHz PCM frames as they arrive.

    Only raw 16 kHz 16-bit mono PCM is declared, which is what the assist
    pipeline sends, so no conversion happens on this side. End of speech is
    left to Home Assistant's VAD (the default `audio_processing`).
    """

    def __init__(self, entry: GradiumConfigEntry) -> None:
        """Read the fallback language from the entry options."""
        super().__init__(entry, "stt")
        self._default_language: str = entry.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE)

    @property
    @override
    def supported_languages(self) -> list[str]:
        """Return the languages Gradium transcribes."""
        return list(SUPPORTED_LANGUAGES)

    @property
    @override
    def supported_formats(self) -> list[AudioFormats]:
        """Return the only container accepted: WAV."""
        return [AudioFormats.WAV]

    @property
    @override
    def supported_codecs(self) -> list[AudioCodecs]:
        """Return the only codec accepted: PCM."""
        return [AudioCodecs.PCM]

    @property
    @override
    def supported_bit_rates(self) -> list[AudioBitRates]:
        """Return the only sample width accepted: 16 bits."""
        return [AudioBitRates.BITRATE_16]

    @property
    @override
    def supported_sample_rates(self) -> list[AudioSampleRates]:
        """Return the only sample rate accepted: 16 kHz, Gradium's pcm_16000."""
        return [AudioSampleRates.SAMPLERATE_16000]

    @property
    @override
    def supported_channels(self) -> list[AudioChannels]:
        """Return the only channel layout accepted: mono."""
        return [AudioChannels.CHANNEL_MONO]

    @override
    async def async_process_audio_stream(
        self, metadata: SpeechMetadata, stream: AsyncIterable[bytes]
    ) -> SpeechResult:
        """Stream the audio to Gradium and return the transcript, "" when nothing was heard.

        Failures become an ERROR result, as the pipeline expects; a refused key
        also starts the reauth flow. Cancellation is never caught.
        """
        settings = SttSettings(language=self._language_for(metadata.language))
        client = self._entry.runtime_data.client
        try:
            text = await client.transcribe(stream, settings)
        except GradiumAuthError as err:
            self._entry.async_start_reauth(self.hass)
            log_gradium_error(err, _ACTION)
            return SpeechResult(None, SpeechResultState.ERROR)
        except GradiumError as err:
            log_gradium_error(err, _ACTION)
            return SpeechResult(None, SpeechResultState.ERROR)

        # Silence or a false wake is not a failure: like the core integrations,
        # return an empty SUCCESS, which the pipeline reports as
        # `stt-no-text-recognized`; ERROR would read as `stt-stream-failed`.
        if not text:
            _LOGGER.debug("Gradium heard no words")
        return SpeechResult(text, SpeechResultState.SUCCESS)

    def _language_for(self, requested: str) -> str:
        """Map "fr-FR" to "fr"; fall back to the configured language when unsupported."""
        language = base_language(requested)
        return language if language in SUPPORTED_LANGUAGES else self._default_language
