from __future__ import annotations

import json
import subprocess
from pathlib import Path

from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.core.errors import DependencyError, RenderError


class WhisperCppTranscriber:
    def __init__(self, binary_path: Path, model_path: Path) -> None:
        self.binary_path = binary_path
        self.model_path = model_path

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptResult:
        if not self.binary_path.exists() or not self.model_path.exists():
            raise DependencyError("whisper.cpp binary or model path does not exist.")
        output = audio_path.with_suffix(".whisper.json")
        command = [str(self.binary_path), "-m", str(self.model_path), "-f", str(audio_path), "-oj", "-of", str(output.with_suffix(""))]
        if language:
            command.extend(["-l", language])
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise DependencyError(f"whisper.cpp binary not runnable: {self.binary_path}") from exc
        except subprocess.CalledProcessError as exc:
            raise RenderError(f"whisper.cpp failed for {audio_path}: {exc.stderr}") from exc
        data = json.loads(output.read_text(encoding="utf-8"))
        segments = [
            TranscriptSegment(item["t0"] / 1000, item["t1"] / 1000, item["text"].strip())
            for item in data.get("transcription", [])
        ]
        return TranscriptResult(language=language or "unknown", segments=segments)
