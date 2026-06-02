from __future__ import annotations

import re

from videotool.ai.transcribe import TranscriptResult

# A chapter heading cue starts with "Chương <number>" (Vietnamese). parse_script keeps a
# blank-line-separated heading as its own cue, so the cue text begins with this marker.
CHAPTER_RE = re.compile(r"^\s*Chương\s+\d+", re.IGNORECASE)

# YouTube chapter rules: first marker at 00:00, at least 3 chapters, each >= 10s apart.
MIN_CHAPTERS = 3
MIN_GAP_SECONDS = 10.0


def derive_chapters(aligned: TranscriptResult) -> list[tuple[float, str]]:
    """Extract (start, title) per chapter from an aligned transcript (W1).

    Chapter starts come from the whisper-aligned cue timing; titles are the verbatim
    heading cue text. Enforces YouTube's chapter constraints — first marker forced to
    00:00, consecutive markers kept only when >= 10s apart, and an empty list when fewer
    than 3 valid chapters remain (so we never emit an invalid chapter block).
    """
    headings = [
        (segment.start, segment.text.strip())
        for segment in aligned.segments
        if CHAPTER_RE.match(segment.text)
    ]
    headings.sort(key=lambda item: item[0])

    spaced: list[tuple[float, str]] = []
    for start, title in headings:
        if not spaced or start >= spaced[-1][0] + MIN_GAP_SECONDS:
            spaced.append((start, title))

    if len(spaced) < MIN_CHAPTERS:
        return []
    # First chapter anchors the video start regardless of the aligned offset.
    spaced[0] = (0.0, spaced[0][1])
    return spaced
