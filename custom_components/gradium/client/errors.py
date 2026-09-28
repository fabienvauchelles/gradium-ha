"""Typed errors raised by the Gradium client.

Every message is meant to be read by a person and never contains the API key.
"""

from __future__ import annotations


def first_line(text: str) -> str:
    """Return the first line of an error text, dropping any footer that follows it."""
    return text.partition("\n")[0].strip()


class GradiumError(Exception):
    """Base error for anything the Gradium client could not carry out."""


class GradiumAuthError(GradiumError):
    """The API key was refused (REST 401 or 403, or a WebSocket 1008 the credit check confirmed)."""


class GradiumCreditsExhaustedError(GradiumError):
    """A request was refused and the account has no credit left; the key itself is valid."""


class GradiumConnectionError(GradiumError):
    """The service could not be reached, or the connection dropped unexpectedly."""


class GradiumTimeoutError(GradiumError):
    """A phase of the exchange exceeded its time budget."""


class GradiumServerError(GradiumError):
    """The service answered, but with an error or with something unusable.

    `code` carries the HTTP status, the WebSocket close code or the code of the
    server's error message when one is known.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        """Store the human readable message and the optional status code."""
        super().__init__(message)
        self.code = code


class GradiumPolicyError(GradiumServerError):
    """A WebSocket refusal with code 1008, not yet told apart from a bad key.

    Gradium uses 1008 for a bad key, a missing subscription, exhausted credits
    and refused requests alike. `GradiumClient` resolves it with a credit read
    into an auth, credits or server error, so it never reaches the adapters.
    `detail` is the server's own reason, without any prefix.
    """

    def __init__(self, message: str, detail: str, code: int | None = None) -> None:
        """Store the message, the server's reason and the close or error code."""
        super().__init__(message, code)
        self.detail = detail
