from __future__ import annotations

from pathlib import Path

from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.core.errors import DependencyError


class FasterWhisperTranscriber:
    def __init__(self, model_path: Path, device: str = "cpu", compute_type: str = "int8") -> None:
        if not model_path.exists():
            raise DependencyError(
                "faster-whisper model path does not exist. Download models explicitly outside VideoTool "
                "and pass the local path with --model."
            )
        self.model_path = model_path
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptResult:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise DependencyError("Install AI extras first: pip install -e '.[ai]'") from exc
        model = WhisperModel(str(self.model_path), device=self.device, compute_type=self.compute_type)
        segments, info = model.transcribe(str(audio_path), language=language, beam_size=5)
        result_segments = [TranscriptSegment(item.start, item.end, item.text.strip()) for item in segments]
        return TranscriptResult(language=info.language or language or "unknown", segments=result_segments)
