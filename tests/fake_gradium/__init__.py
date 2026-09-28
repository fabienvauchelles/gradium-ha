"""A fake Gradium API the integration talks to over real loopback sockets."""

from .behaviors import (
    ERROR_MESSAGE,
    SUPPORT_FOOTER,
    AuthFailure,
    RestFailure,
    SessionRecord,
    SttBehavior,
    SttRecord,
    TtsBehavior,
    TtsRecord,
)
from .server import FakeGradiumServer, RestRequest

__all__ = [
    "ERROR_MESSAGE",
    "SUPPORT_FOOTER",
    "AuthFailure",
    "FakeGradiumServer",
    "RestFailure",
    "RestRequest",
    "SessionRecord",
    "SttBehavior",
    "SttRecord",
    "TtsBehavior",
    "TtsRecord",
]
