"""Shared fixtures.

Gradium is replaced by a fake server on loopback (tests/fake_gradium), and the
integration's client is pointed at it by patching the two module attributes it
reads at construction time: `REGION_ENDPOINTS` and `DEFAULT_TIMEOUTS`. The
client code itself runs for real: headers, paths, JSON, close codes, timeouts.
No test ever reads the real API key file or reaches the network.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.components import ffmpeg, stt, tts
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gradium.client import Region, Timeouts
from custom_components.gradium.client import const as client_const
from custom_components.gradium.const import (
    CONF_LANGUAGE,
    CONF_REGION,
    CONF_TTS_MODEL,
    CONF_VOICE,
    DEFAULT_LANGUAGE,
    DEFAULT_TTS_MODEL,
    DEFAULT_VOICE,
    DOMAIN,
    TITLE,
)

from .fake_gradium import FakeGradiumServer, SessionRecord
from .fixtures import API_KEY, NEW_API_KEY, WRONG_API_KEY, ha_chunks

ENGINE = "tts.gradium"
STT_ENTITY = "stt.gradium"
# WAV is what the entity returns, so Home Assistant never runs ffmpeg in tests.
WAV_OPTIONS = {tts.ATTR_PREFERRED_FORMAT: "wav"}
FAST_TIMEOUTS = Timeouts(connect=2.0, ready=0.3, tts_idle=0.3, stt_flush=0.3, close=0.3)
SECRETS = (API_KEY, NEW_API_KEY, WRONG_API_KEY)
DEFAULT_OPTIONS = {
    CONF_VOICE: DEFAULT_VOICE,
    CONF_TTS_MODEL: DEFAULT_TTS_MODEL,
    CONF_LANGUAGE: DEFAULT_LANGUAGE,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture(autouse=True)
def capture_every_log(caplog: pytest.LogCaptureFixture) -> None:
    """Record debug logs too, so a key leaked at any level fails the leak checks."""
    caplog.set_level(logging.DEBUG)


@pytest.fixture(autouse=True)
def isolated_tts_cache(tmp_path: Path) -> Generator[None]:
    """Keep the TTS file cache under the test's own directory."""
    cache_dir = tmp_path / "tts"
    cache_dir.mkdir()
    with patch.object(tts, "_init_tts_cache_dir", return_value=str(cache_dir)):
        yield


@pytest.fixture(autouse=True)
def no_ffmpeg_probe() -> Generator[None]:
    """TTS depends on ffmpeg, whose setup spawns `ffmpeg -version`; answer it instead.

    No test converts audio: every request asks for WAV, which the entity returns.
    """
    with patch.object(ffmpeg.FFmpegManager, "async_get_version", return_value=("7.1", 7)):
        yield


@pytest.fixture
async def fake_gradium(socket_enabled: None) -> AsyncGenerator[FakeGradiumServer]:
    """A running fake Gradium server, stopped after the test.

    The harness blocks socket creation outright; `socket_enabled` lifts that, while
    its host allow-list still restricts connections to 127.0.0.1.
    """
    server = FakeGradiumServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture(autouse=True)
def gradium_endpoints(monkeypatch: pytest.MonkeyPatch, fake_gradium: FakeGradiumServer) -> None:
    """Send both regions to the fake server."""
    for region in Region:
        monkeypatch.setitem(client_const.REGION_ENDPOINTS, region, fake_gradium.endpoint)


@pytest.fixture
def fast_timeouts(monkeypatch: pytest.MonkeyPatch) -> Timeouts:
    """Shrink the client budgets, for the scenarios that wait for one to run out.

    Request it before `setup_integration`: the client reads the budgets once, at
    construction.
    """
    monkeypatch.setattr(client_const, "DEFAULT_TIMEOUTS", FAST_TIMEOUTS)
    return FAST_TIMEOUTS


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry holding the made-up key, region EU and the default options."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TITLE,
        data={CONF_API_KEY: API_KEY, CONF_REGION: Region.EU.value},
        options=dict(DEFAULT_OPTIONS),
    )


@pytest.fixture
async def setup_integration(hass: HomeAssistant, config_entry: MockConfigEntry) -> MockConfigEntry:
    """The config entry, added and set up against the fake server."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def speak(hass: HomeAssistant, message: str, options: dict[str, Any] | None = None) -> bytes:
    """Render one message as a media player or an automation would, uncached, as WAV."""
    media_id = tts.generate_media_source_id(
        hass, message, ENGINE, "fr", {**WAV_OPTIONS, **(options or {})}, cache=False
    )
    extension, data = await tts.async_get_media_source_audio(hass, media_id)
    assert extension == "wav"
    return data


class HaAudio:
    """An audio stream as the assist pipeline hands it over, counting what was pulled."""

    def __init__(self, pcm: bytes) -> None:
        self.chunks = ha_chunks(pcm)
        self.pulled = 0

    async def stream(self) -> AsyncGenerator[bytes]:
        for chunk in self.chunks:
            self.pulled += 1
            yield chunk


def stt_metadata(language: str = "fr") -> stt.SpeechMetadata:
    """The metadata of the assist pipeline's audio: 16 kHz 16-bit mono PCM."""
    return stt.SpeechMetadata(
        language=language,
        format=stt.AudioFormats.WAV,
        codec=stt.AudioCodecs.PCM,
        bit_rate=stt.AudioBitRates.BITRATE_16,
        sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
        channel=stt.AudioChannels.CHANNEL_MONO,
    )


async def transcribe(
    hass: HomeAssistant, audio: AsyncGenerator[bytes], language: str = "fr"
) -> stt.SpeechResult:
    """Run the stt entity on `audio` the way the assist pipeline does."""
    entity = stt.async_get_speech_to_text_entity(hass, STT_ENTITY)
    assert entity is not None
    async with asyncio.timeout(5):
        return await entity.internal_async_process_audio_stream(stt_metadata(language), audio)


async def session_closed[RecordT: SessionRecord](record: RecordT) -> RecordT:
    """Wait until the fake has seen the session end."""
    async with asyncio.timeout(2):
        await record.closed.wait()
    return record


def reauth_flows(hass: HomeAssistant) -> list[str]:
    """Flow ids of the Gradium reauth flows in progress."""
    return [
        flow["flow_id"]
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        if flow["context"].get("source") == SOURCE_REAUTH
    ]


def assert_key_not_leaked(caplog: pytest.LogCaptureFixture, *texts: str) -> None:
    """Fail when any made-up key shows up in the logs or in one of `texts`."""
    haystacks = (caplog.text, *texts)
    for secret in SECRETS:
        for haystack in haystacks:
            assert secret not in haystack, "an API key leaked"
