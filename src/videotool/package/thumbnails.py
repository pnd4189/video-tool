from __future__ import annotations

import subprocess
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError
from videotool.core.media_probe import probe_media


def generate_thumbnail(video_path: Path, output_path: Path, timestamp: float = 1.0) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        str(output_path),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:
        raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc
    except subprocess.CalledProcessError as exc:
        raise RenderError(f"ffmpeg failed generating thumbnail {output_path.name}: {exc.stderr}") from exc
    return output_path


def generate_thumbnail_candidates(
    video_path: Path,
    output_dir: Path,
    count: int = 5,
    primary_name: str = "thumbnail-1280x720.jpg",
) -> list[Path]:
    """Sample `count` thumbnails spread across the video. First sample is also written
    as the primary thumbnail name expected by the YouTube package validator."""
    if count < 1:
        return []
    duration = probe_media(video_path).duration or 0.0
    # Skip the very first and last few percent — boundary frames are often black/fade.
    if duration <= 2.0:
        timestamps = [max(0.0, duration / 2)]
    else:
        # Evenly spaced inside [5%, 95%] window.
        timestamps = [duration * (0.05 + 0.9 * i / max(1, count - 1)) for i in range(count)]
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for index, ts in enumerate(timestamps, start=1):
        candidate_path = output_dir / f"thumbnail-candidate-{index:02d}.jpg"
        generate_thumbnail(video_path, candidate_path, timestamp=ts)
        results.append(candidate_path)
    # Mirror the first candidate to the canonical name for the package validator.
    primary_path = output_dir / primary_name
    primary_path.write_bytes(results[0].read_bytes())
    return [primary_path, *results]
