"""Robustness paths: time budgets, a server that ignores the close, cancellation.

Each scenario goes through the stt entity or the tts entity against the fake
server and checks both what Home Assistant gets and what is left behind: the
socket closed by the client and no helper task still running.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import AsyncGenerator

import pytest
from homeassistant.components import stt
from homeassistant.components.tts.entity import TextToSpeechEntity, TTSAudioRequest
from homeassistant.components.tts.helper import get_engine_instance
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.gradium.client import Timeouts
from custom_components.gradium.client import const as client_const

from .conftest import ENGINE, FAST_TIMEOUTS, HaAudio, session_closed, speak, transcribe
from .fake_gradium import FakeGradiumServer, SessionRecord, SttBehavior
from .fixtures import SENTENCE, TRANSCRIPT, ha_chunks, speech_pcm

SPEECH_MS = 1250
SHORT_CONNECT = dataclasses.replace(FAST_TIMEOUTS, connect=0.5)
BUDGET_MARGIN = 1.5  # seconds a bounded step may take on a loaded machine
HELPER_TASK_PREFIX = "gradium-"


@pytest.fixture
def short_connect(monkeypatch: pytest.MonkeyPatch) -> Timeouts:
    """Fast budgets with a half-second connect, set before the entry is built."""
    monkeypatch.setattr(client_const, "DEFAULT_TIMEOUTS", SHORT_CONNECT)
    return SHORT_CONNECT


def _helper_tasks() -> list[str]:
    return [
        task.get_name()
        for task in asyncio.all_tasks()
        if task.get_name().startswith(HELPER_TASK_PREFIX) and not task.done()
    ]


async def _until_audio_sent(record: SessionRecord) -> None:
    """Wait until the fake has received at least one audio message."""
    async with asyncio.timeout(2):
        while "audio" not in record.types:
            await asyncio.sleep(0.01)


@pytest.mark.usefixtures("fast_timeouts", "setup_integration")
async def test_stt_ready_timeout_returns_error_within_budget(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """The ASR server never answers setup: ERROR once the ready budget runs out."""
    fake_gradium.stt = SttBehavior.NEVER_READY
    started = time.monotonic()

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())

    assert result.result is stt.SpeechResultState.ERROR
    assert time.monotonic() - started < BUDGET_MARGIN
    record = await session_closed(fake_gradium.stt_sessions[0])
    assert record.types == ["setup"]
    assert record.client_closed
    assert "GradiumTimeoutError" in caplog.text
    assert "ready" in caplog.text


@pytest.mark.usefixtures("short_connect", "setup_integration")
async def test_connect_timeout_fails_both_entities_within_budget(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer
) -> None:
    """The upgrade is never answered: STT returns ERROR and TTS raises timeout, in time."""
    fake_gradium.stall_upgrade = True
    started = time.monotonic()

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())

    assert result.result is stt.SpeechResultState.ERROR
    assert time.monotonic() - started < BUDGET_MARGIN
    started = time.monotonic()
    with pytest.raises(HomeAssistantError) as info:
        await speak(hass, SENTENCE)
    assert info.value.translation_key == "timeout"
    assert "connect" in str(info.value)
    assert time.monotonic() - started < BUDGET_MARGIN
    assert len(fake_gradium.stt_sessions) == len(fake_gradium.tts_sessions) == 1


@pytest.mark.usefixtures("fast_timeouts", "setup_integration")
async def test_server_ignoring_the_close_cannot_hold_the_transcript(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer
) -> None:
    """After flushed the server stops reading: the close is dropped after its budget.

    aiohttp would otherwise wait 10 s for the close reply, past the 5 s the
    `transcribe` helper allows.
    """
    fake_gradium.stt = SttBehavior.IGNORES_CLOSE
    started = time.monotonic()

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())

    elapsed = time.monotonic() - started
    assert result.result is stt.SpeechResultState.SUCCESS
    assert result.text == TRANSCRIPT
    assert elapsed < FAST_TIMEOUTS.close + BUDGET_MARGIN
    [record] = fake_gradium.stt_sessions
    assert record.types[-2:] == ["flush", "end_of_stream"]
    assert not record.client_closed


@pytest.mark.usefixtures("setup_integration")
async def test_cancelled_transcription_closes_the_socket_and_leaves_no_task(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer
) -> None:
    """The pipeline is cancelled while the microphone is still open."""
    first_chunks = ha_chunks(speech_pcm(SPEECH_MS))
    never = asyncio.Event()

    async def microphone() -> AsyncGenerator[bytes]:
        for chunk in first_chunks:
            yield chunk
        await never.wait()
        yield b""

    task = asyncio.create_task(transcribe(hass, microphone()))
    while not fake_gradium.stt_sessions:
        await asyncio.sleep(0.01)
    await _until_audio_sent(fake_gradium.stt_sessions[0])
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    record = await session_closed(fake_gradium.stt_sessions[0])
    assert record.client_closed
    assert "flush" not in record.types
    assert _helper_tasks() == []


@pytest.mark.usefixtures("setup_integration")
async def test_cancelled_synthesis_closes_the_socket_and_leaves_no_task(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer
) -> None:
    """The consumer of the audio is cancelled while the text is still being written."""
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
    pulled: list[bytes] = []

    async def consume() -> None:
        async for chunk in response.data_gen:
            pulled.append(chunk)

    task = asyncio.create_task(consume())
    async with asyncio.timeout(2):
        while len(pulled) < 2:  # the WAV header, then the first audio chunk
            await asyncio.sleep(0.01)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    record = await session_closed(fake_gradium.tts_sessions[0])
    assert record.client_closed
    assert "end_of_stream" not in record.types
    assert _helper_tasks() == []
