from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError


@dataclass(frozen=True)
class SilenceRange:
    start: float
    end: float


def detect_silence(audio_path: Path, threshold: str = "-35dB", min_duration: float = 0.5) -> list[SilenceRange]:
    command = [
        "ffmpeg",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=noise={threshold}:d={min_duration}",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=600)
    except FileNotFoundError as exc:
        raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"silencedetect timed out for {audio_path}") from exc
    # ffmpeg prints analysis to stderr even on success; only treat negative returncode
    # (signal-terminated) or returncode > 0 with empty stderr as a hard failure.
    if result.returncode != 0 and not result.stderr:
        raise RenderError(f"ffmpeg silencedetect failed for {audio_path} (exit {result.returncode})")
    starts = [float(match) for match in re.findall(r"silence_start: ([0-9.]+)", result.stderr)]
    ends = [float(match) for match in re.findall(r"silence_end: ([0-9.]+)", result.stderr)]
    return [SilenceRange(start, end) for start, end in zip(starts, ends, strict=False)]


def write_cut_suggestions(ranges: list[SilenceRange], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Cut Suggestions", "", "Review these ranges manually before editing.", ""]
    lines.extend(f"- {item.start:.3f}s to {item.end:.3f}s" for item in ranges)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
