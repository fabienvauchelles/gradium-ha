"""Facade over the Gradium REST and WebSocket APIs, the only class the HA layer builds."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable
from contextlib import aclosing

import aiohttp

from . import const
from .errors import GradiumPolicyError
from .models import Credits, Region, SttSettings, Timeouts, TtsSettings, Voice
from .refusal import resolve_refusal
from .rest import GradiumRestApi, parse_credits, parse_voices
from .stt import GradiumSttSession
from .tts import GradiumTtsSession


class GradiumClient:
    """Gradium client bound to one API key and one region.

    The aiohttp session belongs to the caller (HA's shared session) and is
    never closed here. Each TTS or STT call opens its own WebSocket. A refusal
    with code 1008 is resolved here, after the socket is closed, into
    `GradiumAuthError`, `GradiumCreditsExhaustedError` or `GradiumServerError`.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        region: Region,
        *,
        timeouts: Timeouts | None = None,
    ) -> None:
        """Resolve the region endpoint and the time budgets at build time."""
        self._session = session
        self._api_key = api_key
        self._region = region
        # Looked up through the module on purpose: tests patch both attributes.
        self._endpoint = const.REGION_ENDPOINTS[region]
        self._timeouts = timeouts if timeouts is not None else const.DEFAULT_TIMEOUTS
        self._rest = GradiumRestApi(session, api_key, self._endpoint, self._timeouts.connect)

    def __repr__(self) -> str:
        """Describe the client without its API key."""
        return f"GradiumClient(region={self._region.value!r})"

    @property
    def region(self) -> Region:
        """Region the client talks to."""
        return self._region

    async def async_get_credits(self) -> Credits:
        """Read the credit balance; as an authenticated read, it also checks the key."""
        payload = await self._rest.get_json(const.CREDITS_PATH)
        return parse_credits(payload)

    async def async_list_voices(self) -> list[Voice]:
        """List the catalogue voices and the organisation's own voices."""
        payload = await self._rest.get_json(const.VOICES_PATH, const.VOICES_PARAMS)
        return parse_voices(payload)

    def synthesize(self, text: AsyncIterable[str], settings: TtsSettings) -> AsyncGenerator[bytes]:
        """Stream raw PCM s16le mono at `settings.sample_rate` for the streamed text.

        Chunks (80 ms each) are yielded as received. Nothing is opened until
        the first chunk is pulled; closing the generator closes the socket.
        """
        session = GradiumTtsSession(
            self._session, self._api_key, self._endpoint, self._timeouts, settings
        )
        return self._resolving_refusals(session.stream(text))

    async def transcribe(self, audio: AsyncIterable[bytes], settings: SttSettings) -> str:
        """Transcribe raw PCM s16le mono 16 kHz audio given in chunks of any size.

        Returns the stripped transcript, "" when nothing was recognised.
        """
        session = GradiumSttSession(
            self._session, self._api_key, self._endpoint, self._timeouts, settings
        )
        try:
            return await session.run(audio)
        except GradiumPolicyError as err:
            raise await resolve_refusal(err, self.async_get_credits) from err

    async def _resolving_refusals(self, audio: AsyncGenerator[bytes]) -> AsyncGenerator[bytes]:
        """Pass the audio through, resolving a 1008 refusal; closing this closes `audio`."""
        async with aclosing(audio):
            try:
                async for chunk in audio:
                    yield chunk
            except GradiumPolicyError as err:
                raise await resolve_refusal(err, self.async_get_credits) from err
