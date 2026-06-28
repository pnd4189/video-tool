from __future__ import annotations

import os
from pathlib import Path

from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.core.errors import DependencyError


def _looks_like_path(model: str) -> bool:
    """A bare HuggingFace model id (e.g. ``large-v3``) has no path separator.

    Anything with a separator is treated as a local path so typos still error
    instead of silently triggering a network download.
    """
    return os.sep in model or "/" in model


class FasterWhisperTranscriber:
    def __init__(self, model_path: str | Path, device: str = "cpu", compute_type: str = "int8") -> None:
        model_ref = str(model_path)
        # A value that looks like a local path must exist; a bare model id is passed
        # straight to WhisperModel as a HuggingFace name (downloaded on demand).
        if _looks_like_path(model_ref) and not Path(model_ref).exists():
            raise DependencyError(
                "faster-whisper model path does not exist. Download models explicitly outside VideoTool "
                "and pass the local path with --model, or pass a HuggingFace model id like 'large-v3'."
            )
        self.model_ref = model_ref
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyError("Install AI extras first: pip install -e '.[ai]'") from exc
        model = WhisperModel(self.model_ref, device=self.device, compute_type=self.compute_type)
        segments, info = model.transcribe(str(audio_path), language=language, beam_size=5)
        result_segments = [TranscriptSegment(item.start, item.end, item.text.strip()) for item in segments]
        return TranscriptResult(language=info.language or language or "unknown", segments=result_segments)
