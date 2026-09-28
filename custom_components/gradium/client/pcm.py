"""Raw PCM helpers: WAV header for streamed output, fixed-size framing for input."""

from __future__ import annotations

import struct

from .const import STT_FRAME_BYTES

_PCM_FORMAT_TAG = 1
_FMT_CHUNK_SIZE = 16
# RIFF size of a WAV file whose data chunk is empty: everything after "RIFF<size>".
_EMPTY_RIFF_SIZE = 36


def wav_header(sample_rate: int, channels: int = 1, sample_width: int = 2) -> bytes:
    """Build a 44-byte PCM WAV header with a data size of 0.

    A size of 0 is the streaming form HA's own Wyoming TTS sends: the length of
    the audio is unknown when the header goes out.
    """
    block_align = channels * sample_width
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        _EMPTY_RIFF_SIZE,
        b"WAVE",
        b"fmt ",
        _FMT_CHUNK_SIZE,
        _PCM_FORMAT_TAG,
        channels,
        sample_rate,
        sample_rate * block_align,
        block_align,
        sample_width * 8,
        b"data",
        0,
    )


class PcmFramer:
    """Regroup PCM chunks of any size into frames of exactly `frame_bytes`."""

    def __init__(self, frame_bytes: int = STT_FRAME_BYTES) -> None:
        """Start with an empty buffer."""
        if frame_bytes <= 0:
            raise ValueError(f"frame_bytes must be positive, got {frame_bytes}")
        self._frame_bytes = frame_bytes
        self._buffer = bytearray()

    def push(self, chunk: bytes) -> list[bytes]:
        """Add a chunk and return every frame now complete, in order."""
        self._buffer.extend(chunk)
        size = self._frame_bytes
        count = len(self._buffer) // size
        frames = [bytes(self._buffer[i * size : (i + 1) * size]) for i in range(count)]
        del self._buffer[: count * size]
        return frames

    def finish(self) -> bytes | None:
        """Return the remainder zero-padded to a full frame, or None if nothing is left."""
        if not self._buffer:
            return None
        frame = bytes(self._buffer) + b"\x00" * (self._frame_bytes - len(self._buffer))
        self._buffer.clear()
        return frame
