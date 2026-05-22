from __future__ import annotations

import math
import subprocess
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError
from videotool.core.media_probe import probe_media

DEFAULT_CROSSFADE_SECONDS = 2.0
# Hard ceiling on the number of music inputs concatenated via acrossfade. With short
# music + very long videos this can grow large; cap to prevent pathological ffmpeg
# command lines and surface the situation as a user-actionable error instead.
MAX_PLAYS = 200
SUBPROCESS_TIMEOUT_SECONDS = 1800


def prepare_seamless_music(
    music_path: Path,
    target_duration: float,
    workspace_root: Path,
    crossfade_seconds: float = DEFAULT_CROSSFADE_SECONDS,
) -> Path:
    """Pre-render a music track to exactly `target_duration` seconds with crossfaded
    seams between loop iterations and a fade-out tail. Returns the path of the
    prepared FLAC inside `workspace_root`.

    The output replaces the original music input in the main render. Because the
    file already covers the full video length, the main render's `-stream_loop -1`
    on the music input never triggers a loop (the output ends first), so the
    audible seam from raw repetition is eliminated.
    """
    if target_duration <= 0:
        raise RenderError(
            f"prepare_seamless_music: target_duration must be positive, got {target_duration}"
        )
    music_meta = probe_media(music_path)
    music_duration = music_meta.duration or 0.0
    if music_duration <= 0:
        raise RenderError(f"prepare_seamless_music: could not probe duration: {music_path}")

    workspace_root.mkdir(parents=True, exist_ok=True)
    output = workspace_root / "music-loop.flac"

    if music_duration >= target_duration:
        command = _build_trim_command(music_path, output, target_duration, crossfade_seconds)
    else:
        # Keep crossfade short relative to a single play so the music does not feel like
        # it is fading in/out at every seam.
        crossfade = min(crossfade_seconds, music_duration / 4)
        plays = math.ceil((target_duration - crossfade) / (music_duration - crossfade))
        plays = max(2, plays)
        if plays > MAX_PLAYS:
            raise RenderError(
                f"Music track too short ({music_duration:.1f}s) for target {target_duration:.1f}s. "
                f"Would need {plays} loops (cap {MAX_PLAYS}). Use a longer music track."
            )
        command = _build_loop_command(music_path, output, target_duration, crossfade, plays)

    _run(command)
    return output


def _build_trim_command(music_path: Path, output: Path, target: float, crossfade: float) -> list[str]:
    fade_start = max(0.0, target - crossfade)
    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        "-i", str(music_path),
        "-t", f"{target:.3f}",
        "-af", f"afade=t=out:st={fade_start:.3f}:d={crossfade:.3f}",
        "-c:a", "flac", "-compression_level", "5",
        str(output),
    ]


def _build_loop_command(music_path: Path, output: Path, target: float, crossfade: float, plays: int) -> list[str]:
    inputs: list[str] = []
    for _ in range(plays):
        inputs.extend(["-i", str(music_path)])

    filter_parts: list[str] = []
    current = "0:a"
    for i in range(1, plays):
        label = f"x{i}" if i < plays - 1 else "joined"
        filter_parts.append(
            f"[{current}][{i}:a]acrossfade=d={crossfade:.3f}:curve1=tri:curve2=tri[{label}]"
        )
        current = label

    fade_start = max(0.0, target - crossfade)
    filter_parts.append(
        f"[joined]atrim=duration={target:.3f},"
        f"afade=t=out:st={fade_start:.3f}:d={crossfade:.3f}[out]"
    )

    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "[out]",
        "-c:a", "flac", "-compression_level", "5",
        str(output),
    ]


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Seamless music loop preparation timed out.") from exc
    if result.returncode != 0:
        raise RenderError(
            f"FFmpeg failed preparing seamless music loop (exit {result.returncode}):\n{result.stderr}"
        )
