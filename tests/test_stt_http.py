"""Speech-to-text through Home Assistant's STT HTTP view, against the fake server.

The view checks the request's `X-Speech-Content` against what the entity
declares before any audio is read, and answers 415 when the language tag is
not listed as is. A client posting the whole body at once, speech from its
very first sample, is also the case where a first word is easiest to lose.
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import STT_ENTITY, session_closed
from .fake_gradium import FakeGradiumServer
from .fixtures import STT_FRAME_BYTES, STT_LEAD_IN_FRAMES, TRANSCRIPT, speech_pcm

SPEECH_MS = 1250
STT_URL = f"/api/stt/{STT_ENTITY}"
pytestmark = pytest.mark.usefixtures("setup_integration")


def _speech_content(language: str) -> dict[str, str]:
    """The header of a 16 kHz 16-bit mono PCM upload in `language`."""
    return {
        "X-Speech-Content": (
            f"format=wav; codec=pcm; sample_rate=16000; bit_rate=16; channel=1; language={language}"
        )
    }


@pytest.mark.parametrize(
    ("requested", "sent"),
    [("fr-FR", "fr"), ("fr-BE", "fr"), ("fr", "fr"), ("en-GB", "en"), ("pt-BR", "pt")],
)
async def test_region_tagged_language_is_accepted_and_sent_as_its_base_code(
    hass: HomeAssistant,
    fake_gradium: FakeGradiumServer,
    hass_client: ClientSessionGenerator,
    requested: str,
    sent: str,
) -> None:
    """A region tag passes Home Assistant's check; the speech reaches the server whole.

    The speech starts at its first sample and is posted in one body. The server
    gets the silent lead-in first, then every byte of the speech in order.
    """
    pcm = speech_pcm(SPEECH_MS)
    assert pcm[:2] != bytes(2)
    client = await hass_client()

    response = await client.post(STT_URL, data=pcm, headers=_speech_content(requested))

    assert response.status == HTTPStatus.OK
    assert await response.json() == {"text": TRANSCRIPT, "result": "success"}
    record = await session_closed(fake_gradium.stt_sessions[0])
    assert record.setup["json_config"]["language"] == sent
    lead_in, speech = record.frames[:STT_LEAD_IN_FRAMES], record.frames[STT_LEAD_IN_FRAMES:]
    assert lead_in == [bytes(STT_FRAME_BYTES)] * STT_LEAD_IN_FRAMES
    assert speech[0] == pcm[:STT_FRAME_BYTES]
    assert b"".join(speech)[: len(pcm)] == pcm


async def test_declared_languages_list_region_variants(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """The view lists every base code followed by its region-tagged variants."""
    client = await hass_client()

    response = await client.get(STT_URL)

    assert response.status == HTTPStatus.OK
    languages = (await response.json())["languages"]
    assert languages[:2] == ["fr", "fr-FR"]
    assert {"fr-CA", "fr-CH", "en-US", "de-DE", "es-ES", "pt-PT"} <= set(languages)


async def test_unsupported_language_is_refused_before_any_session(
    hass: HomeAssistant, fake_gradium: FakeGradiumServer, hass_client: ClientSessionGenerator
) -> None:
    """A language Gradium does not transcribe is refused with 415, and nothing is opened."""
    client = await hass_client()

    response = await client.post(
        STT_URL, data=speech_pcm(SPEECH_MS), headers=_speech_content("it-IT")
    )

    assert response.status == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
    assert fake_gradium.stt_sessions == []
