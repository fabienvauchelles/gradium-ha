"""A fake Gradium API on loopback: REST routes and the two WebSocket endpoints.

It runs on an aiohttp TestServer bound to 127.0.0.1, which the Home Assistant
test harness lets through its socket guard, so the integration's real client
code runs end to end against it: the headers it sets, the paths it builds, the
JSON it sends, the way it reads close codes.

Auth mirrors the behaviour described in docs/protocol.md for a wrong key:
REST answers 401 `{"detail": "Invalid or expired API key"}`; a WebSocket
upgrade succeeds, then the server sends an error message with code 1008 and
closes with 1008. `AuthFailure.BARE_CLOSE` plays the missing-key variant, a
close 1008 with no JSON.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import WSCloseCode, WSMsgType, web
from aiohttp.test_utils import TestServer

from custom_components.gradium.client import Endpoint

from ..fixtures import API_KEY, REMAINING_CREDITS, credits_payload, voices_payload
from .behaviors import (
    AuthFailure,
    RestFailure,
    SessionRecord,
    SttBehavior,
    SttRecord,
    TtsBehavior,
    TtsRecord,
    with_footer,
)
from .stt_handler import SttPlayer
from .tts_handler import TtsPlayer

API_KEY_HEADER = "x-api-key"
AUTH_FAILURE = "Invalid or expired API key"
CLOSE_HANDSHAKE_TIMEOUT = 2.0

type MessageHandler = Callable[[web.WebSocketResponse, dict[str, Any]], Awaitable[bool]]


@dataclass(frozen=True)
class RestRequest:
    """One REST call as the server saw it. The key itself is never kept."""

    path: str
    query: dict[str, str]
    authorized: bool


class FakeGradiumServer:
    """Scriptable stand-in for eu.api.gradium.ai / api.gradium.ai."""

    def __init__(self) -> None:
        self.valid_key = API_KEY
        self.auth_failure = AuthFailure.ERROR_MESSAGE
        self.remaining_credits = REMAINING_CREDITS
        self.stall_upgrade = False  # hold every WebSocket upgrade until the server stops
        self.rest_failure = RestFailure.NONE
        self.tts = TtsBehavior.NORMAL
        self.stt = SttBehavior.NORMAL
        self.rest_requests: list[RestRequest] = []
        self.tts_sessions: list[TtsRecord] = []
        self.stt_sessions: list[SttRecord] = []
        self._server: TestServer | None = None
        self._release = asyncio.Event()

    @property
    def endpoint(self) -> Endpoint:
        """Where the integration's client must point to reach this server."""
        assert self._server is not None, "fake Gradium server not started"
        port = self._server.port
        return Endpoint(f"http://127.0.0.1:{port}/api", f"ws://127.0.0.1:{port}/api")

    async def start(self) -> None:
        """Bind the server on a free loopback port."""
        app = web.Application()
        app.router.add_get("/api/voices/", self._voices)
        app.router.add_get("/api/usages/credits", self._credits)
        app.router.add_get("/api/speech/tts", self._tts_socket)
        app.router.add_get("/api/speech/asr", self._asr_socket)
        self._server = TestServer(app, host="127.0.0.1")
        await self._server.start_server()

    async def stop(self) -> None:
        """Shut the server down; stalled handlers are released, open sockets closed."""
        self._release.set()
        if self._server is not None:
            await self._server.close()

    def _authorized(self, request: web.Request) -> bool:
        return request.headers.get(API_KEY_HEADER) == self.valid_key

    async def _voices(self, request: web.Request) -> web.Response:
        return self._rest(request, voices_payload())

    async def _credits(self, request: web.Request) -> web.Response:
        return self._rest(request, credits_payload(self.remaining_credits))

    def _rest(self, request: web.Request, payload: Any) -> web.Response:
        authorized = self._authorized(request)
        self.rest_requests.append(RestRequest(request.path, dict(request.query), authorized))
        if self.rest_failure is RestFailure.SERVER_ERROR:
            return web.json_response({"detail": "Internal Server Error"}, status=500)
        if not authorized:
            return web.json_response({"detail": AUTH_FAILURE}, status=401)
        return web.json_response(payload)

    async def _tts_socket(self, request: web.Request) -> web.StreamResponse:
        record = TtsRecord(path=request.path, authorized=self._authorized(request))
        self.tts_sessions.append(record)
        return await self._serve(request, record, TtsPlayer(self.tts, record).on_message)

    async def _asr_socket(self, request: web.Request) -> web.StreamResponse:
        record = SttRecord(path=request.path, authorized=self._authorized(request))
        self.stt_sessions.append(record)
        player = SttPlayer(self.stt, record, self._release)
        return await self._serve(request, record, player.on_message)

    async def _serve(
        self, request: web.Request, record: SessionRecord, handler: MessageHandler
    ) -> web.StreamResponse:
        """Accept the upgrade, then play the session until either side ends it."""
        if self.stall_upgrade:
            await self._release.wait()
            record.closed.set()
            return web.Response(status=503)
        if not record.authorized and self.auth_failure is AuthFailure.UPGRADE_REFUSED:
            record.closed.set()
            return web.json_response({"detail": AUTH_FAILURE}, status=401)
        ws = web.WebSocketResponse(max_msg_size=0, timeout=CLOSE_HANDSHAKE_TIMEOUT)
        await ws.prepare(request)
        return await _run_session(ws, record, handler, self.auth_failure)


async def _run_session(
    ws: web.WebSocketResponse,
    record: SessionRecord,
    handler: MessageHandler,
    auth_failure: AuthFailure,
) -> web.WebSocketResponse:
    """Play an accepted session, keeping a transport failure on the record."""
    try:
        await _play(ws, record, handler, auth_failure)
    except ConnectionResetError as err:
        # The client went away under a send. Kept on the record, where a test can see it.
        record.transport_error = f"{type(err).__name__}: {err}"
    finally:
        record.closed.set()
    return ws


async def _play(
    ws: web.WebSocketResponse,
    record: SessionRecord,
    handler: MessageHandler,
    auth_failure: AuthFailure,
) -> None:
    if not record.authorized:
        code = WSCloseCode.POLICY_VIOLATION
        if auth_failure is AuthFailure.ERROR_MESSAGE:
            error = {"type": "error", "client_req_id": None, "message": with_footer(AUTH_FAILURE)}
            await ws.send_json({**error, "code": int(code)})
        await ws.close(code=code, message=AUTH_FAILURE.encode())
        return
    async for message in ws:
        if message.type is not WSMsgType.TEXT:
            break
        data = json.loads(message.data)
        record.messages.append(data)
        if await handler(ws, data):
            return
    # The loop ends on the client's close frame, which aiohttp answers on its own.
    record.client_closed = ws.closed
