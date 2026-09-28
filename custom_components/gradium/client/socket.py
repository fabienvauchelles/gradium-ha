"""One Gradium WebSocket: JSON messages in and out, failures mapped to typed errors.

A bad API key does not fail the upgrade: the server accepts it, then sends a
JSON error with code 1008 and closes with 1008 (a missing key closes with 1008
and no JSON). Code 1008 also covers a missing subscription, exhausted credits
and requests refused on policy, and only the free-text message differs, so
every 1008 becomes a `GradiumPolicyError` that the client resolves with a
credit read. Guessing from the text would either miss a bad key or start a
reauth that accepts the same key and loops.

Error messages carry only the detail of what went wrong: the error class, and
the message Home Assistant shows for it, name the failure once.
"""

from __future__ import annotations

import asyncio
import json
import logging
from http import HTTPStatus
from typing import Any, Self

import aiohttp

from .const import (
    API_KEY_HEADER,
    CLOSE_INTERNAL_ERROR,
    CLOSE_POLICY_VIOLATION,
    CLOSE_PROTOCOL_ERROR,
)
from .errors import (
    GradiumAuthError,
    GradiumConnectionError,
    GradiumError,
    GradiumPolicyError,
    GradiumServerError,
    GradiumTimeoutError,
)
from .models import Timeouts

_LOGGER = logging.getLogger(__name__)

_AUTH_STATUSES = {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
_SERVER_CLOSE_CODES = {CLOSE_PROTOCOL_ERROR, CLOSE_INTERNAL_ERROR}
# The outer bound of close(), above aiohttp's own ws_close so that one fires first.
_CLOSE_GUARD_FACTOR = 2
_CLOSE_TYPES = {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED}


def close_error(code: int | None, reason: str | None = None) -> GradiumError:
    """Map a close that came without a JSON error message to a typed error."""
    detail = f"close code {code}" + (f": {reason}" if reason else "")
    if code == CLOSE_POLICY_VIOLATION:
        return GradiumPolicyError(detail, detail, code)
    if code in _SERVER_CLOSE_CODES:
        return GradiumServerError(f"connection closed on an error ({detail})", code)
    return GradiumConnectionError(f"connection closed unexpectedly ({detail})")


def error_message_error(message: dict[str, Any]) -> GradiumError:
    """Map a `{"type": "error"}` message to a typed error; code 1008 is left to resolve."""
    text = str(message.get("message") or "no message")
    code = message.get("code")
    code = code if isinstance(code, int) and not isinstance(code, bool) else None
    if code == CLOSE_POLICY_VIOLATION:
        return GradiumPolicyError(text, text, code)
    return GradiumServerError(text, code)


class GradiumSocket:
    """A connected Gradium WebSocket exchanging JSON messages."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse, close_timeout: float) -> None:
        """Wrap an already connected WebSocket."""
        self._ws = ws
        self._close_timeout = close_timeout

    @classmethod
    async def connect(
        cls, session: aiohttp.ClientSession, url: str, api_key: str, timeouts: Timeouts
    ) -> Self:
        """Open the WebSocket at `url`, authenticated with the API key header.

        `ws_close` bounds the wait for the server's close frame, which aiohttp
        otherwise waits 10 s for; past it aiohttp drops the connection.
        """
        timeout = timeouts.connect
        ws_timeout = aiohttp.ClientWSTimeout(ws_receive=None, ws_close=timeouts.close)
        try:
            async with asyncio.timeout(timeout):
                ws = await session.ws_connect(
                    url,
                    headers={API_KEY_HEADER: api_key},
                    heartbeat=None,
                    max_msg_size=0,
                    timeout=ws_timeout,
                )
        except TimeoutError as err:
            raise GradiumTimeoutError(f"no connection within {timeout} s (connect)") from err
        except aiohttp.WSServerHandshakeError as err:
            if err.status in _AUTH_STATUSES:
                raise GradiumAuthError(f"HTTP {err.status} on the WebSocket upgrade") from err
            raise GradiumConnectionError(
                f"WebSocket upgrade refused with HTTP {err.status}"
            ) from err
        except aiohttp.ClientError as err:
            raise GradiumConnectionError(str(err) or type(err).__name__) from err
        return cls(ws, timeouts.close)

    async def send(self, message: dict[str, Any]) -> None:
        """Send one JSON message."""
        try:
            await self._ws.send_str(json.dumps(message))
        except (aiohttp.ClientError, ConnectionError) as err:
            raise GradiumConnectionError(f"send failed: {err}") from err

    async def receive(self, timeout: float | None, *, phase: str = "receive") -> dict[str, Any]:
        """Receive the next JSON message, waiting at most `timeout` seconds.

        `None` waits without limit. `phase` names the step in a timeout error.
        """
        try:
            async with asyncio.timeout(timeout):
                msg = await self._ws.receive()
        except TimeoutError as err:
            raise GradiumTimeoutError(f"no message within {timeout} s ({phase})") from err
        if msg.type is aiohttp.WSMsgType.TEXT:
            return _parse_text(msg.data)
        if msg.type is aiohttp.WSMsgType.CLOSE:
            raise close_error(msg.data, msg.extra)
        if msg.type in _CLOSE_TYPES:
            raise close_error(self._ws.close_code)
        if msg.type is aiohttp.WSMsgType.ERROR:
            raise GradiumConnectionError(f"connection failed: {msg.data}")
        raise GradiumServerError(f"unexpected {msg.type.name} message")

    async def close(self) -> None:
        """Close the WebSocket without ever holding the caller up for long.

        Does nothing when it is already closed. `ws_close` covers a server that
        never answers the close frame; this outer bound also covers sending ours
        to a server that stopped reading. Either way the connection is dropped,
        which is the purpose of a close, and the session's outcome is already
        known, so running out of time here is logged, not raised.
        """
        if self._ws.closed:
            return
        budget = self._close_timeout * _CLOSE_GUARD_FACTOR
        try:
            async with asyncio.timeout(budget):
                await self._ws.close()
        except TimeoutError:
            _LOGGER.debug("Gradium socket dropped: the close did not complete in %s s", budget)


def _parse_text(data: str) -> dict[str, Any]:
    """Decode a text frame into a message dict, raising on an error message."""
    try:
        message = json.loads(data)
    except ValueError as err:
        raise GradiumServerError("a message is not valid JSON") from err
    if not isinstance(message, dict):
        raise GradiumServerError("a JSON message is not an object")
    if message.get("type") == "error":
        raise error_message_error(message)
    return message
