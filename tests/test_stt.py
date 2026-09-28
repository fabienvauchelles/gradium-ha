"""Speech-to-text through Home Assistant's stt entity, against the fake server.

Audio is fed the way the assist pipeline does it: 16 kHz mono PCM in 10 ms
chunks of 320 bytes, which the integration regroups into Gradium's 80 ms
frames of 2560 bytes, after a short silent lead-in.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator

import pytest
from homeassistant.components import stt
from homeassistant.core import HomeAssistant

from .conftest import HaAudio, assert_key_not_leaked, reauth_flows, session_closed, transcribe
from .fake_gradium import FakeGradiumServer, SttBehavior
from .fixtures import (
    HA_CHUNK_BYTES,
    STT_FRAME_BYTES,
    STT_LEAD_IN_FRAMES,
    TRANSCRIPT,
    ha_chunks,
    speech_pcm,
)

SPEECH_MS = 1250  # 15 full frames and a 1600-byte remainder
LONG_SPEECH_MS = 4000
pytestmark = pytest.mark.usefixtures("setup_integration")


async def test_speech_is_framed_flushed_and_transcribed(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Silent lead-in, then 80 ms frames, the tail zero-padded, flush at once, end_of_stream."""
    pcm = speech_pcm(SPEECH_MS)
    audio = HaAudio(pcm)
    assert len(audio.chunks[0]) == HA_CHUNK_BYTES

    result = await transcribe(hass, audio.stream())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == TRANSCRIPT
    assert audio.pulled == len(audio.chunks)
    [record] = fake_gradium.stt_sessions
    record = await session_closed(record)
    assert record.authorized
    assert record.setup["model_name"] == "default"
    assert record.setup["input_format"] == "pcm_16000"
    assert record.setup["json_config"] == {"language": "fr", "delay_in_frames": 7}

    lead_in, speech = record.frames[:STT_LEAD_IN_FRAMES], record.frames[STT_LEAD_IN_FRAMES:]
    assert lead_in == [bytes(STT_FRAME_BYTES)] * STT_LEAD_IN_FRAMES
    full_frames, remainder = divmod(len(pcm), STT_FRAME_BYTES)
    assert remainder
    assert len(speech) == full_frames + 1
    assert all(len(frame) == STT_FRAME_BYTES for frame in speech)
    assert b"".join(speech)[: len(pcm)] == pcm
    assert speech[-1][remainder:] == bytes(STT_FRAME_BYTES - remainder)

    # No silent drain frames between the speech and the flush.
    audio_count = len(record.frames)
    assert record.types == ["setup", *["audio"] * audio_count, "flush", "end_of_stream"]
    assert record.of_type("flush")[0]["flush_id"] == 1
    assert_key_not_leaked(caplog)


@pytest.mark.parametrize(
    ("requested", "sent"),
    [("fr-FR", "fr"), ("en-US", "en"), ("de", "de"), ("it-IT", "fr")],
)
async def test_pipeline_language_is_reduced_to_a_gradium_language(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, requested: str, sent: str
) -> None:
    """Region tags are dropped; an unsupported language falls back to the configured one."""
    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream(), requested)

    assert result.result is stt.SpeechResultState.SUCCESS
    [record] = fake_gradium.stt_sessions
    assert record.setup["json_config"]["language"] == sent


async def test_server_error_mid_stream_stops_reading_the_microphone(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """After an error message the integration stops pulling audio and returns ERROR."""
    fake_gradium.stt = SttBehavior.ERROR_MID_STREAM
    chunks = ha_chunks(speech_pcm(LONG_SPEECH_MS))
    chunks_per_frame = STT_FRAME_BYTES // HA_CHUNK_BYTES
    gate = 3 * chunks_per_frame  # the fake fails on the third frame
    pulled = 0

    async def microphone() -> AsyncGenerator[bytes]:
        nonlocal pulled
        for index, chunk in enumerate(chunks):
            if index == gate:
                # Let the error reach the client before more audio is offered.
                await fake_gradium.stt_sessions[0].error_sent.wait()
                await asyncio.sleep(0.05)
            pulled += 1
            yield chunk
            await asyncio.sleep(0)

    result = await transcribe(hass, microphone())

    assert result.result is stt.SpeechResultState.ERROR
    assert pulled < len(chunks)
    assert pulled <= gate + chunks_per_frame
    assert reauth_flows(hass) == []
    assert_key_not_leaked(caplog)


@pytest.mark.usefixtures("fast_timeouts")
async def test_missing_flushed_returns_error_within_the_flush_budget(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer
) -> None:
    """The server never answers the flush: ERROR once the flush budget runs out."""
    fake_gradium.stt = SttBehavior.NEVER_FLUSHED
    started = time.monotonic()

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())

    assert result.result is stt.SpeechResultState.ERROR
    assert time.monotonic() - started < 2
    record = await session_closed(fake_gradium.stt_sessions[0])
    assert "flush" in record.types
    assert record.client_closed


async def test_silence_is_an_empty_success(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing heard (silence, false wake): an empty SUCCESS, as the core integrations return.

    The assist pipeline turns it into `stt-no-text-recognized`; an ERROR would be
    reported as `stt-stream-failed`. Nothing is logged above debug.
    """
    fake_gradium.stt = SttBehavior.EMPTY_TRANSCRIPT

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())

    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == ""
    record = await session_closed(fake_gradium.stt_sessions[0])
    assert record.types[-2:] == ["flush", "end_of_stream"]
    assert not [
        entry
        for entry in caplog.records
        if entry.levelno >= logging.WARNING and entry.name.startswith("custom_components.gradium")
    ]
