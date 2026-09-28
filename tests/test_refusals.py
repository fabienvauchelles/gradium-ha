"""WebSocket refusals with close code 1008, through the stt and tts entities.

Gradium closes with 1008 for a bad key and for every other refusal (missing
subscription, no credit left, request refused on policy), with or without an
error message first, and only the free text tells them apart. The integration
settles it with a credit read: refused, the key is bad and a reauth starts; an
empty balance is a typed credits error; anything else is a server error. The
last two never start a reauth, which would accept the same key and loop. The
fake's refusal text is the same in every case on purpose: it must not matter.
"""

from __future__ import annotations

import pytest
from homeassistant.components import stt
from homeassistant.components.tts import ATTR_VOICE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import (
    HaAudio,
    assert_key_not_leaked,
    reauth_flows,
    session_closed,
    speak,
    transcribe,
)
from .fake_gradium import (
    AuthFailure,
    FakeGradiumServer,
    RestFailure,
    RestRequest,
    SttBehavior,
    TtsBehavior,
)
from .fixtures import NEW_API_KEY, SENTENCE, speech_pcm

SPEECH_MS = 1250
CREDITS_PATH = "/api/usages/credits"
POLICY_TEXT = "Missing subscription"
pytestmark = pytest.mark.usefixtures("setup_integration")


def _credit_reads(fake_gradium: FakeGradiumServer) -> list[RestRequest]:
    return [request for request in fake_gradium.rest_requests if request.path == CREDITS_PATH]


def _revoke_key(fake_gradium: FakeGradiumServer, auth_failure: AuthFailure) -> None:
    """The stored key stops working after setup, refused the given way."""
    fake_gradium.valid_key = NEW_API_KEY
    fake_gradium.auth_failure = auth_failure


@pytest.mark.parametrize("auth_failure", [AuthFailure.ERROR_MESSAGE, AuthFailure.BARE_CLOSE])
async def test_bad_key_on_stt_returns_error_and_starts_reauth(
    hass: HomeAssistant,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
    auth_failure: AuthFailure,
) -> None:
    """1008 on the ASR socket, with or without JSON, and a refused credit read: reauth."""
    _revoke_key(fake_gradium, auth_failure)

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())
    await hass.async_block_till_done()

    assert result.result is stt.SpeechResultState.ERROR
    assert result.text is None
    [record] = fake_gradium.stt_sessions
    assert not record.authorized
    [check] = _credit_reads(fake_gradium)
    assert not check.authorized
    assert len(reauth_flows(hass)) == 1
    assert "GradiumAuthError" in caplog.text
    assert_key_not_leaked(caplog)


@pytest.mark.parametrize("auth_failure", [AuthFailure.ERROR_MESSAGE, AuthFailure.BARE_CLOSE])
async def test_bad_key_on_tts_raises_invalid_auth_and_starts_reauth(
    hass: HomeAssistant,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
    auth_failure: AuthFailure,
) -> None:
    """1008 on the TTS socket, with or without JSON, and a refused credit read: invalid_auth."""
    _revoke_key(fake_gradium, auth_failure)

    with pytest.raises(HomeAssistantError) as info:
        await speak(hass, SENTENCE)
    await hass.async_block_till_done()

    assert info.value.translation_key == "invalid_auth"
    [record] = fake_gradium.tts_sessions
    assert not record.authorized
    [check] = _credit_reads(fake_gradium)
    assert not check.authorized
    assert len(reauth_flows(hass)) == 1
    assert_key_not_leaked(caplog, str(info.value))


async def test_no_credit_left_on_stt_returns_error_without_reauth(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid key, refusal with code 1008, empty balance: ERROR and a credits error in the log."""
    fake_gradium.stt = SttBehavior.POLICY_REFUSED
    fake_gradium.remaining_credits = 0

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())
    await hass.async_block_till_done()

    assert result.result is stt.SpeechResultState.ERROR
    record = await session_closed(fake_gradium.stt_sessions[0])
    assert record.authorized
    [check] = _credit_reads(fake_gradium)
    assert check.authorized
    assert reauth_flows(hass) == []
    assert "GradiumCreditsExhaustedError" in caplog.text
    assert_key_not_leaked(caplog)


async def test_no_credit_left_on_tts_raises_credits_exhausted_without_reauth(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid key, refusal with code 1008, empty balance: credits_exhausted, no reauth."""
    fake_gradium.tts = TtsBehavior.POLICY_REFUSED
    fake_gradium.remaining_credits = 0

    with pytest.raises(HomeAssistantError) as info:
        await speak(hass, SENTENCE)
    await hass.async_block_till_done()

    assert info.value.translation_key == "credits_exhausted"
    assert POLICY_TEXT in str(info.value)
    assert len(_credit_reads(fake_gradium)) == 1
    assert reauth_flows(hass) == []
    assert_key_not_leaked(caplog, str(info.value))


async def test_policy_refusal_on_stt_returns_error_without_reauth(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Valid key, credits left, refusal with code 1008: ERROR, the server's text logged."""
    fake_gradium.stt = SttBehavior.POLICY_REFUSED

    result = await transcribe(hass, HaAudio(speech_pcm(SPEECH_MS)).stream())
    await hass.async_block_till_done()

    assert result.result is stt.SpeechResultState.ERROR
    record = await session_closed(fake_gradium.stt_sessions[0])
    assert record.error_sent.is_set()
    assert len(_credit_reads(fake_gradium)) == 1
    assert reauth_flows(hass) == []
    assert "refused the API key" not in caplog.text
    assert "GradiumServerError" in caplog.text
    assert POLICY_TEXT in caplog.text
    assert_key_not_leaked(caplog)


@pytest.mark.parametrize("rest_failure", [RestFailure.NONE, RestFailure.SERVER_ERROR])
async def test_policy_refusal_on_tts_raises_server_error_without_reauth(
    hass: HomeAssistant,
    fake_gradium: FakeGradiumServer,
    caplog: pytest.LogCaptureFixture,
    rest_failure: RestFailure,
) -> None:
    """Refusal with code 1008 and credits left, or a credit read that fails: server_error."""
    fake_gradium.tts = TtsBehavior.POLICY_REFUSED
    fake_gradium.rest_failure = rest_failure

    with pytest.raises(HomeAssistantError) as info:
        await speak(hass, SENTENCE, {ATTR_VOICE: "unknown-voice"})
    await hass.async_block_till_done()

    assert info.value.translation_key == "server_error"
    record = await session_closed(fake_gradium.tts_sessions[0])
    assert record.authorized
    assert record.setup["voice_id"] == "unknown-voice"
    assert len(_credit_reads(fake_gradium)) == 1
    assert reauth_flows(hass) == []
    assert POLICY_TEXT in str(info.value)
    assert_key_not_leaked(caplog, str(info.value))
