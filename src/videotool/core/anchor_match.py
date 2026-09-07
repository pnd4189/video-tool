"""Turn each planned scene's narration excerpt into the second it is spoken.

The excerpt in the scene plan is copied verbatim out of the QA'd narration, and the SRT is
that same narration with timings attached — so finding the excerpt inside the SRT text finds
the scene in time. Within the cue that holds it, the position is interpolated by character
offset; narration speed is near-constant (measured 13-18 chars/sec across an episode), so a
character offset maps to a time offset closely enough for placing an image.

Matching walks a forward cursor: scene i is searched from where scene i-1 matched. That keeps
results in story order for free and picks the right occurrence when a sentence repeats, which
no amount of scoring a single match in isolation can do.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from videotool.ai.subtitles import _timestamp_to_seconds

# Quote characters vary between the plan and the SRT (straight vs curly), so they are dropped
# on both sides rather than trusted to agree.
_QUOTES_RE = re.compile(r"[\"'`‘’“”«»]")
_SPACE_RE = re.compile(r"\s+")
# Word counts tried when the full excerpt does not match — the usual cause is the proofread
# changing a word or two after the plan was written, which leaves the opening intact.
PREFIX_WORD_FALLBACKS = (8, 6, 5)


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class MatchReport:
    """How the anchors fared, for the one-line report the storyboard step prints."""

    exact: int = 0
    prefix: int = 0
    missing: int = 0

    @property
    def matched(self) -> int:
        return self.exact + self.prefix

    @property
    def total(self) -> int:
        return self.matched + self.missing


def normalize(text: str) -> str:
    """Fold the incidental differences between the plan's excerpt and the SRT's wording.

    Vietnamese diacritics are deliberately preserved — stripping them invents matches between
    words that are not the same word.
    """
    folded = unicodedata.normalize("NFC", text).lower()
    return _SPACE_RE.sub(" ", _QUOTES_RE.sub("", folded)).strip()


def parse_srt_cues(srt_text: str) -> list[Cue]:
    """Every timed cue of an SRT, in order.

    The timestamp line is located by its ``-->`` rather than assumed to be the second line, so
    a hand-edited SRT with a stray blank line still parses.
    """
    normalized = srt_text.replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in normalized.strip().split("\n\n"):
        lines = block.splitlines()
        index = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if index is None or index + 1 >= len(lines):
            continue
        start_text, _, end_text = lines[index].partition(" --> ")
        cues.append(
            Cue(
                start=_timestamp_to_seconds(start_text.strip()),
                end=_timestamp_to_seconds(end_text.strip()),
                text=normalize(" ".join(lines[index + 1:])),
            )
        )
    return cues


def locate_anchors(anchors: list[str], cues: list[Cue]) -> tuple[list[float | None], MatchReport]:
    """Second at which each anchor is spoken, or None where it could not be found.

    Returns one entry per anchor, in the order given, so the caller can line them up with its
    scenes. A None never blocks anything: the caller spaces the unlocated scenes between their
    nearest located neighbours, which confines one bad anchor to its own neighbourhood.
    """
    if not cues:
        return [None] * len(anchors), MatchReport(missing=len(anchors))

    body, offsets = _build_index(cues)
    times: list[float | None] = []
    exact = prefix = missing = 0
    cursor = 0
    for anchor in anchors:
        needle = normalize(anchor)
        position = body.find(needle, cursor) if needle else -1
        if position >= 0:
            exact += 1
        else:
            position = _find_prefix(body, needle, cursor)
            if position >= 0:
                prefix += 1
        if position < 0:
            times.append(None)
            missing += 1
            continue
        cursor = position + 1
        times.append(_time_at(position, cues, offsets))
    return times, MatchReport(exact=exact, prefix=prefix, missing=missing)


def _build_index(cues: list[Cue]) -> tuple[str, list[int]]:
    """The cue texts joined into one searchable string, plus each cue's offset into it."""
    offsets: list[int] = []
    parts: list[str] = []
    cursor = 0
    for cue in cues:
        offsets.append(cursor)
        parts.append(cue.text)
        cursor += len(cue.text) + 1  # +1 for the space the join inserts
    return " ".join(parts), offsets


def _find_prefix(body: str, needle: str, cursor: int) -> int:
    """Locate a shortened opening of the anchor, trying progressively fewer words."""
    words = needle.split()
    for count in PREFIX_WORD_FALLBACKS:
        if len(words) < count:
            continue
        position = body.find(" ".join(words[:count]), cursor)
        if position >= 0:
            return position
    return -1


def _time_at(position: int, cues: list[Cue], offsets: list[int]) -> float:
    """Interpolate the second a character offset falls on, inside the cue that holds it."""
    import bisect

    index = max(bisect.bisect_right(offsets, position) - 1, 0)
    cue = cues[index]
    span = max(len(cue.text), 1)
    fraction = min(1.0, max(0.0, (position - offsets[index]) / span))
    return cue.start + fraction * (cue.end - cue.start)
