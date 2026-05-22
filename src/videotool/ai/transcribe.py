from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    language: str
    segments: list[TranscriptSegment]


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptResult:
        ...
