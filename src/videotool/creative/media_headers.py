"""Media length from a file's first bytes: the WAV RIFF header and the MP4/M4A `mvhd` box."""

from __future__ import annotations

import struct


def wav_seconds(head: bytes) -> float | None:
    """Duration from the RIFF header alone: walk the chunks (a LIST chunk may precede `data`)."""
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return None
    pos, byte_rate = 12, None
    while pos + 8 <= len(head):
        chunk_id, size = head[pos:pos + 4], struct.unpack("<I", head[pos + 4:pos + 8])[0]
        if chunk_id == b"fmt " and pos + 20 <= len(head):
            byte_rate = struct.unpack("<I", head[pos + 16:pos + 20])[0]
        if chunk_id == b"data":
            return size / byte_rate if byte_rate else None
        pos += 8 + size + (size & 1)
    return None


def mvhd_seconds(head: bytes) -> float | None:
    """Duration from an MP4/M4A `mvhd` box at the head of the file (faststart)."""
    i = head.find(b"mvhd")
    while i >= 4 and struct.unpack(">I", head[i - 4:i])[0] not in (108, 120):
        i = head.find(b"mvhd", i + 4)  # the 4 bytes happened to occur inside media data
    if i < 4 or i + 36 > len(head):
        return None
    version = head[i + 4]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", head[i + 24:i + 36])
    else:
        timescale, duration = struct.unpack(">II", head[i + 16:i + 24])
    return duration / timescale if timescale else None
