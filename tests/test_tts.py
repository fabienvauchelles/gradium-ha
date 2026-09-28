"""Text-to-speech through Home Assistant's tts component, against the fake server.

Every request asks for WAV (`preferred_format`), the format the entity returns,
so Home Assistant never needs ffmpeg and the bytes it hands back are exactly
the entity's output: a streaming WAV header, then Gradium's PCM.
"""

from __future__ import annotations

import asyncio
import re
import struct
import time
from collections.abc import AsyncGenerator

import pytest
from homeassistant.components import tts
from homeassistant.components.tts.entity import TextToSpeechEntity, TTSAudioRequest
from homeassistant.components.tts.helper import get_engine_instance
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gradium.const import ATTR_MODEL

from .conftest import (
    ENGINE,
    WAV_OPTIONS,
    assert_key_not_leaked,
    reauth_flows,
    session_closed,
    speak,
)
from .fake_gradium import ERROR_MESSAGE, FakeGradiumServer, TtsBehavior, TtsRecord
from .fixtures import CLAIRE, GASPARD, SENTENCE

WAV_HEADER_BYTES = 44
PUNCTUATION_ONLY = re.compile(r"[\s?!:;,.]*")
STREAM_DELTAS_BEFORE_GATE = ("Bonjour, je suis", " ta mai", "son. Comment vas", "-tu ", "?")
STREAM_DELTAS_AFTER_GATE = (" Très bien, merci", " !")
pytestmark = pytest.mark.usefixtures("setup_integration")


def _normalized(text: str) -> str:
    """Single spaces, and no space before punctuation (French puts one before ? and !)."""
    return re.sub(r"\s+([?!:;,.])", r"\1", " ".join(text.split()))


def _texts(record: TtsRecord) -> list[str]:
    return [str(message["text"]) for message in record.of_type("text")]


async def test_message_is_rendered_as_48khz_wav_from_gradium_audio(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """A plain message: default voice and model, WAV header, then the PCM as sent."""
    data = await speak(hass, SENTENCE)

    assert data[:4] == b"RIFF"
    assert data[8:16] == b"WAVEfmt "
    channels, sample_rate = struct.unpack_from("<HI", data, 22)
    (bits,) = struct.unpack_from("<H", data, 34)
    assert (channels, sample_rate, bits) == (1, 48000, 16)
    assert data[36:40] == b"data"

    [record] = fake_gradium.tts_sessions
    assert record.authorized
    assert record.setup["voice_id"] == GASPARD
    assert record.setup["model_name"] == "default"
    assert record.setup["output_format"] == "pcm_48000"
    assert record.audio_sent
    assert data[WAV_HEADER_BYTES:] == b"".join(record.audio_sent)
    assert _normalized(" ".join(_texts(record))) == _normalized(SENTENCE)
    assert record.types[-1] == "end_of_stream"
    await session_closed(record)
    assert record.transport_error is None
    assert_key_not_leaked(caplog)


async def test_streamed_message_is_sent_as_whole_words_and_speaks_early(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """LLM-style deltas split words and isolate a `?`; audio flows before the text ends."""
    gate = asyncio.Event()

    async def message_gen() -> AsyncGenerator[str]:
        for delta in STREAM_DELTAS_BEFORE_GATE:
            yield delta
        await gate.wait()
        for delta in STREAM_DELTAS_AFTER_GATE:
            yield delta

    stream = tts.async_create_stream(hass, ENGINE, "fr", dict(WAV_OPTIONS))
    stream.async_set_message_stream(message_gen())
    chunks: list[bytes] = []
    async with asyncio.timeout(5):
        async for chunk in stream.async_stream_result():
            chunks.append(chunk)
            if len(chunks) == 2:
                # First PCM chunk after the header, while the text is still open.
                gate.set()

    assert len(fake_gradium.tts_sessions) == 1
    record = await session_closed(fake_gradium.tts_sessions[0])
    full_text = "".join(STREAM_DELTAS_BEFORE_GATE + STREAM_DELTAS_AFTER_GATE)
    texts = _texts(record)
    assert len(texts) > 1
    for text in texts:
        assert text == text.strip()
        assert not PUNCTUATION_ONLY.fullmatch(text), f"punctuation sent alone: {text!r}"
    assert _normalized(" ".join(texts)) == _normalized(full_text)
    assert b"".join(chunks)[WAV_HEADER_BYTES:] == b"".join(record.audio_sent)
    assert record.types[-1] == "end_of_stream"
    assert_key_not_leaked(caplog)


async def test_per_call_options_override_the_defaults(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer
) -> None:
    """The `voice` and `model` options of one call reach the setup message."""
    await speak(hass, SENTENCE, {tts.ATTR_VOICE: CLAIRE, ATTR_MODEL: "gradium-tts-beta"})

    [record] = fake_gradium.tts_sessions
    assert record.setup["voice_id"] == CLAIRE
    assert record.setup["model_name"] == "gradium-tts-beta"


async def test_error_after_first_audio_raises_server_error(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """An error message mid-synthesis fails the request instead of truncating it silently."""
    fake_gradium.tts = TtsBehavior.ERROR_AFTER_FIRST_AUDIO

    with pytest.raises(HomeAssistantError) as info:
        await speak(hass, SENTENCE)

    assert info.value.translation_key == "server_error"
    assert str(info.value) == f"Gradium reported an error: {ERROR_MESSAGE}"
    assert reauth_flows(hass) == []
    record = await session_closed(fake_gradium.tts_sessions[0])
    assert record.error_sent.is_set()
    assert_key_not_leaked(caplog, str(info.value))


@pytest.mark.usefixtures("fast_timeouts")
@pytest.mark.parametrize("behavior", [TtsBehavior.NEVER_READY, TtsBehavior.SILENT_AFTER_EOS])
async def test_silent_server_raises_timeout(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, behavior: TtsBehavior
) -> None:
    """No ready, or no end after end_of_stream: the request fails within its budget."""
    fake_gradium.tts = behavior
    started = time.monotonic()

    with pytest.raises(HomeAssistantError) as info:
        await speak(hass, SENTENCE)

    assert info.value.translation_key == "timeout"
    assert time.monotonic() - started < 2
    record = await session_closed(fake_gradium.tts_sessions[0])
    assert record.client_closed


async def test_consumer_stopping_early_closes_the_socket(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer
) -> None:
    """Closing the audio stream mid-way closes the Gradium socket at once."""
    never = asyncio.Event()

    async def endless_message() -> AsyncGenerator[str]:
        yield "Il était une fois, dans un salon très calme, "
        await never.wait()
        yield "jamais."

    engine = get_engine_instance(hass, ENGINE)
    assert isinstance(engine, TextToSpeechEntity)
    response = await engine.internal_async_stream_tts_audio(
        TTSAudioRequest(language="fr", options={}, message_gen=endless_message())
    )
    async with asyncio.timeout(5):
        header = await anext(response.data_gen)
        first_audio = await anext(response.data_gen)
    await response.data_gen.aclose()

    assert len(header) == WAV_HEADER_BYTES
    record = await session_closed(fake_gradium.tts_sessions[0])
    assert first_audio == record.audio_sent[0]
    assert record.client_closed
    assert "end_of_stream" not in record.types
