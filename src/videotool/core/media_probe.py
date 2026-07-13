from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videotool.core.errors import DependencyError, ValidationError


@dataclass(frozen=True)
class MediaMetadata:
    path: Path
    duration: float
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None


def probe_media(path: Path) -> MediaMetadata:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=True)
    except FileNotFoundError as exc:
        raise DependencyError("ffprobe was not found. Install FFmpeg 6.1+ and retry.") from exc
    except subprocess.CalledProcessError as exc:
        raise ValidationError(f"ffprobe failed for {path}: {exc.stderr.strip()}") from exc
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"ffprobe returned invalid JSON for {path}") from exc
    duration = float(data.get("format", {}).get("duration") or 0)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fps = _parse_fps(video.get("avg_frame_rate"))
    return MediaMetadata(
        path=path,
        duration=duration,
        width=video.get("width"),
        height=video.get("height"),
        fps=fps,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name"),
        sample_rate=int(audio["sample_rate"]) if audio.get("sample_rate") else None,
    )


def _parse_fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)
    return float(value)
