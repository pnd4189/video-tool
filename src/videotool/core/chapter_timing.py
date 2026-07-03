from __future__ import annotations

import re

from videotool.ai.subtitles import _timestamp_to_seconds
from videotool.ai.transcribe import TranscriptResult

# A chapter heading cue starts with "Chương <number>" (Vietnamese). parse_script keeps a
# blank-line-separated heading as its own cue, so the cue text begins with this marker.
CHAPTER_RE = re.compile(r"^\s*Chương\s+\d+", re.IGNORECASE)
# Quotes/spaces some SRT exporters prepend to a heading cue (e.g. '" Chương 143:').
_HEADING_LEAD = " \t\"'“”‘’"

# YouTube chapter rules: first marker at 00:00, at least 3 chapters, each >= 10s apart.
MIN_CHAPTERS = 3
MIN_GAP_SECONDS = 10.0


def _enforce_youtube_chapter_rules(headings: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Sort headings by time, drop markers closer than MIN_GAP_SECONDS, force the first to
    00:00, and return an empty list when fewer than MIN_CHAPTERS survive (never emit an
    invalid chapter block). Shared by the whisper and provided-SRT paths."""
    headings = sorted(headings, key=lambda item: item[0])
    spaced: list[tuple[float, str]] = []
    for start, title in headings:
        if not spaced or start >= spaced[-1][0] + MIN_GAP_SECONDS:
            spaced.append((start, title))
    if len(spaced) < MIN_CHAPTERS:
        return []
    spaced[0] = (0.0, spaced[0][1])
    return spaced


def derive_chapters(aligned: TranscriptResult) -> list[tuple[float, str]]:
    """Extract (start, title) per chapter from an aligned transcript (W1).

    Chapter starts come from the whisper-aligned cue timing; titles are the verbatim
    heading cue text. Enforces YouTube's chapter constraints via _enforce_youtube_chapter_rules.
    """
    headings = [
        (segment.start, segment.text.strip())
        for segment in aligned.segments
        if CHAPTER_RE.match(segment.text)
    ]
    return _enforce_youtube_chapter_rules(headings)


def chapters_from_srt(srt_text: str) -> list[tuple[float, str]]:
    """Extract chapters directly from a provided SRT (no whisper). A heading cue's text
    begins with "Chương <number>" (after stripping any leading quote/space some exporters
    add); its start timestamp anchors the chapter. Same YouTube constraints as derive_chapters.
    """
    normalized = srt_text.replace("\r\n", "\n").replace("\r", "\n")
    headings: list[tuple[float, str]] = []
    for block in normalized.strip().split("\n\n"):
        lines = block.splitlines()
        # Locate the timestamp line instead of assuming index 1: tolerates stray blank lines
        # or an extra index line so a hand-edited SRT never silently drops a chapter.
        ts_idx = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if ts_idx is None or ts_idx + 1 >= len(lines):
            continue
        title = " ".join(line.strip() for line in lines[ts_idx + 1:]).lstrip(_HEADING_LEAD)
        if not CHAPTER_RE.match(title):
            continue
        start = _timestamp_to_seconds(lines[ts_idx].split(" --> ", 1)[0].strip())
        headings.append((start, title))
    return _enforce_youtube_chapter_rules(headings)
