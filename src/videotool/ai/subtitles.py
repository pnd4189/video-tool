from __future__ import annotations

import textwrap
from pathlib import Path

from videotool.ai.transcribe import TranscriptResult, TranscriptSegment


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def segment_to_srt(index: int, segment: TranscriptSegment) -> str:
    text = "\n".join(textwrap.wrap(segment.text, width=42)) if segment.text else ""
    return f"{index}\n{format_srt_timestamp(segment.start)} --> {format_srt_timestamp(segment.end)}\n{text}\n"


def write_srt(transcript: TranscriptResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = [segment_to_srt(index, segment) for index, segment in enumerate(transcript.segments, start=1)]
    path.write_text("\n".join(blocks), encoding="utf-8")


def validate_srt(path: Path) -> list[str]:
    if not path.exists():
        return [f"SRT file is missing: {path}"]
    errors: list[str] = []
    last_start = -1.0
    # Normalize line endings so Whisper exports written on Windows (CRLF) parse the same
    # as those written on Linux. Otherwise blocks are split incorrectly and every block
    # looks malformed.
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    for block in raw.strip().split("\n\n"):
        lines = block.splitlines()
        if len(lines) < 3 or " --> " not in lines[1]:
            errors.append(f"Invalid SRT block: {lines[:2]}")
            continue
        start = _timestamp_to_seconds(lines[1].split(" --> ", 1)[0])
        if start < last_start:
            errors.append("SRT timestamps must be ordered.")
        last_start = start
    return errors


def _timestamp_to_seconds(value: str) -> float:
    hms, ms = value.split(",", 1)
    hours, minutes, seconds = [int(part) for part in hms.split(":")]
    return hours * 3600 + minutes * 60 + seconds + int(ms) / 1000
