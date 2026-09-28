"""Scripted failure modes of the fake Gradium server and what it records.

A test picks a behaviour before it drives Home Assistant, then reads the
records afterwards to assert what went over the wire: every JSON message the
integration sent, the audio frames it pushed, and whether it closed the socket.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from aiohttp import WSCloseCode, web

ERROR_MESSAGE = "Internal failure"
POLICY_MESSAGE = "Missing subscription"


class AuthFailure(Enum):
    """How a WebSocket refuses a bad key once the upgrade has succeeded."""

    ERROR_MESSAGE = auto()  # error message code 1008, then close 1008 (wrong key)
    BARE_CLOSE = auto()  # close 1008 with no JSON (missing key)


class RestFailure(Enum):
    """How the REST routes answer, whatever the key."""

    NONE = auto()
    SERVER_ERROR = auto()  # 500 on every REST route


class TtsBehavior(Enum):
    """How the TTS WebSocket handler plays a session."""

    NORMAL = auto()
    ERROR_AFTER_FIRST_AUDIO = auto()  # one audio chunk, then an error message and close 1011
    NEVER_READY = auto()  # setup is read and never answered
    SILENT_AFTER_EOS = auto()  # the client's end_of_stream is never answered
    POLICY_REFUSED = auto()  # setup answered with an error message code 1008, then close 1008


class SttBehavior(Enum):
    """How the ASR WebSocket handler plays a session."""

    NORMAL = auto()
    ERROR_MID_STREAM = auto()  # an error message and close 1011 after a few frames
    NEVER_FLUSHED = auto()  # words are sent, flush is never answered
    EMPTY_TRANSCRIPT = auto()  # no word at all, flush answered normally
    POLICY_REFUSED = auto()  # setup answered with an error message code 1008, then close 1008
    NEVER_READY = auto()  # setup is read and never answered
    IGNORES_CLOSE = auto()  # after end_of_stream the server stops reading: no close reply


@dataclass
class SessionRecord:
    """One WebSocket session as the server saw it."""

    path: str
    authorized: bool
    messages: list[dict[str, Any]] = field(default_factory=list)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    client_closed: bool = False  # the client sent the close frame first
    error_sent: asyncio.Event = field(default_factory=asyncio.Event)
    transport_error: str | None = None  # the socket died under a send, recorded for asserts

    def of_type(self, kind: str) -> list[dict[str, Any]]:
        """Client messages of one type, in arrival order."""
        return [message for message in self.messages if message.get("type") == kind]

    @property
    def types(self) -> list[str]:
        """Type of every client message, in arrival order."""
        return [str(message.get("type")) for message in self.messages]

    @property
    def setup(self) -> dict[str, Any]:
        """The setup message; fails the test when the client never sent one."""
        setups = self.of_type("setup")
        assert setups, f"no setup message on {self.path}"
        return setups[0]


@dataclass
class TtsRecord(SessionRecord):
    """A TTS session: the audio chunks the server sent, in order."""

    audio_sent: list[bytes] = field(default_factory=list)


@dataclass
class SttRecord(SessionRecord):
    """An ASR session: the decoded audio frames the client pushed, in order."""

    frames: list[bytes] = field(default_factory=list)


async def send_error(ws: web.WebSocketResponse, record: SessionRecord) -> None:
    """Fail the session the way the real server does: an error message, then close 1011."""
    code = WSCloseCode.INTERNAL_ERROR
    await ws.send_json({"type": "error", "message": ERROR_MESSAGE, "code": int(code)})
    record.error_sent.set()
    await ws.close(code=code, message=ERROR_MESSAGE.encode())


async def send_policy_refusal(ws: web.WebSocketResponse, record: SessionRecord) -> None:
    """Refuse a request on policy with a valid key: an error message code 1008, then close 1008."""
    code = WSCloseCode.POLICY_VIOLATION
    await ws.send_json({"type": "error", "message": POLICY_MESSAGE, "code": int(code)})
    record.error_sent.set()
    await ws.close(code=code, message=POLICY_MESSAGE.encode())
