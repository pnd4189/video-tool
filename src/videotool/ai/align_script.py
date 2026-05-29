from __future__ import annotations

import re
from pathlib import Path

from videotool.ai.transcribe import TranscriptResult, TranscriptSegment

# A sentence is a run of text up to (and including) any terminal punctuation.
# Works on generic prose; a heading line without terminal punctuation is one cue.
SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]*")
PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


def parse_script(path: Path) -> list[str]:
    """Split a plain-prose script into ordered sentence cues.

    Paragraphs are separated by blank lines; within a paragraph, sentences split on
    ``. ! ? …``. No heading or filename special-casing — a title line is simply the
    first cue. Empty fragments are dropped; order is preserved.
    """
    text = path.read_text(encoding="utf-8")
    cues: list[str] = []
    for block in PARAGRAPH_SPLIT_RE.split(text):
        paragraph = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if not paragraph:
            continue
        cues.extend(match.strip() for match in SENTENCE_RE.findall(paragraph) if match.strip())
    return cues


def align_script_to_transcript(
    script_sentences: list[str],
    transcript: TranscriptResult,
) -> TranscriptResult:
    """Re-time the polished script onto whisper's timing.

    Whisper segment spans are the clock: their concatenated durations form the
    speaking timeline (gaps/silence are skipped). Each script sentence claims a slice
    of that timeline proportional to its character length, then maps back to real
    timestamps. Cues stay monotonic, non-overlapping, and bounded by the whisper span.
    """
    if not script_sentences or not transcript.segments:
        return transcript

    spans = [(segment.start, segment.end) for segment in transcript.segments]
    total_speaking = sum(end - start for start, end in spans)
    lengths = [max(1, len(sentence)) for sentence in script_sentences]
    total_chars = sum(lengths)

    segments: list[TranscriptSegment] = []
    char_cursor = 0
    for sentence, length in zip(script_sentences, lengths):
        start = _time_at(char_cursor / total_chars * total_speaking, spans)
        char_cursor += length
        end = _time_at(char_cursor / total_chars * total_speaking, spans)
        segments.append(TranscriptSegment(start=start, end=max(start, end), text=sentence))
    return TranscriptResult(language=transcript.language, segments=segments)


def _time_at(speaking_offset: float, spans: list[tuple[float, float]]) -> float:
    """Map a cumulative-speaking-time offset back to a real timestamp by walking spans."""
    accumulated = 0.0
    for start, end in spans:
        duration = end - start
        if speaking_offset <= accumulated + duration:
            return start + (speaking_offset - accumulated)
        accumulated += duration
    return spans[-1][1]
