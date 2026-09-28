"""Batch streamed text deltas into whole words for the TTS WebSocket.

The server inserts a space between two `text` messages, so a message must never
end in the middle of a word, and punctuation must never travel alone (it would
be read as a separate word). French typography puts a space before `?`, `!`,
`:` and `;`, which makes punctuation-only tokens common in streamed text.
"""

from __future__ import annotations

import unicodedata


def _is_punctuation(token: str) -> bool:
    """True when every character of the token is a Unicode punctuation mark."""
    return all(unicodedata.category(char).startswith("P") for char in token)


class WordChunker:
    """Turn text deltas into space-joined runs of whole words.

    The last complete word is held back until the next word has started, so a
    punctuation token that follows it (after a space) is still attached to it.
    """

    def __init__(self) -> None:
        """Start with nothing buffered."""
        self._partial = ""
        self._held: str | None = None
        self._held_is_punctuation = False

    def push(self, delta: str) -> str | None:
        """Add a delta and return the whole words now safe to send, if any."""
        text = self._partial + delta
        tokens = text.split()
        self._partial = ""
        if tokens and not text[-1].isspace():
            self._partial = tokens.pop()
        out: list[str] = []
        for token in tokens:
            self._accept(token, out)
        if self._partial and not _is_punctuation(self._partial):
            self._release_word(out)
        return " ".join(out) or None

    def flush(self) -> str | None:
        """Return everything still buffered, including the held word, if any."""
        out: list[str] = []
        if self._partial:
            self._accept(self._partial, out)
            self._partial = ""
        if self._held is not None:
            out.append(self._held)
            self._held = None
            self._held_is_punctuation = False
        return " ".join(out) or None

    def _accept(self, token: str, out: list[str]) -> None:
        """Take one complete token, emitting the previously held word when due."""
        if self._held is None:
            self._held = token
            self._held_is_punctuation = _is_punctuation(token)
            return
        if _is_punctuation(token) or self._held_is_punctuation:
            self._held = f"{self._held} {token}"
            self._held_is_punctuation = self._held_is_punctuation and _is_punctuation(token)
            return
        out.append(self._held)
        self._held = token
        self._held_is_punctuation = False

    def _release_word(self, out: list[str]) -> None:
        """Emit the held word once a following word has started arriving."""
        if self._held is None or self._held_is_punctuation:
            return
        out.append(self._held)
        self._held = None
