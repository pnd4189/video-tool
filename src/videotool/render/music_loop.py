from __future__ import annotations

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
    music_paths: list[Path],
    target_duration: float,
    workspace_root: Path,
    crossfade_seconds: float = DEFAULT_CROSSFADE_SECONDS,
) -> Path:
    """Pre-render a music bed to exactly `target_duration` seconds with crossfaded seams and
    a fade-out tail. Returns the path of the prepared FLAC inside `workspace_root`.

    `music_paths` are played back-to-back in the given order; the sequence repeats (loops
    from the first track) until it covers `target_duration`. Heterogeneous sample rates /
    channel layouts are normalized before crossfading. The output replaces the original music
    input in the main render — because it already covers the full video length, the render's
    `-stream_loop -1` never triggers, eliminating the audible seam from raw repetition.
    """
    if target_duration <= 0:
        raise RenderError(
            f"prepare_seamless_music: target_duration must be positive, got {target_duration}"
        )
    if not music_paths:
        raise RenderError("prepare_seamless_music: no music tracks provided")

    durations: list[float] = []
    for path in music_paths:
        duration = probe_media(path).duration or 0.0
        if duration <= 0:
            raise RenderError(f"prepare_seamless_music: could not probe duration: {path}")
        durations.append(duration)

    workspace_root.mkdir(parents=True, exist_ok=True)
    output = workspace_root / "music-loop.flac"

    if len(music_paths) == 1 and durations[0] >= target_duration:
        command = _build_trim_command(music_paths[0], output, target_duration, crossfade_seconds)
    else:
        # Keep crossfade short relative to the shortest track so seams do not feel like a
        # fade in/out at every join.
        crossfade = min(crossfade_seconds, min(durations) / 4)
        sequence = _build_sequence(music_paths, durations, target_duration, crossfade)
        if len(sequence) > MAX_PLAYS:
            raise RenderError(
                f"Music tracks too short for target {target_duration:.1f}s. Would need "
                f"{len(sequence)} segments (cap {MAX_PLAYS}). Use longer music tracks."
            )
        command = _build_loop_command(sequence, output, target_duration, crossfade)

    _run(command)
    return output


def _build_sequence(
    music_paths: list[Path], durations: list[float], target: float, crossfade: float
) -> list[Path]:
    """Cycle the tracks in order until their crossfaded length covers `target`.

    The first segment contributes its full duration; each subsequent segment adds its
    duration minus one crossfade (the overlap). Always emits at least two segments so the
    loop command's acrossfade chain has something to join.
    """
    sequence: list[Path] = [music_paths[0]]
    covered = durations[0]
    index = 1
    while covered < target or len(sequence) < 2:
        track = index % len(music_paths)
        sequence.append(music_paths[track])
        covered += durations[track] - crossfade
        index += 1
        if len(sequence) > MAX_PLAYS:
            break
    return sequence


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


def _build_loop_command(sequence: list[Path], output: Path, target: float, crossfade: float) -> list[str]:
    inputs: list[str] = []
    for path in sequence:
        inputs.extend(["-i", str(path)])

    filter_parts: list[str] = []
    # Normalize each segment so acrossfade can join tracks with differing rates/layouts.
    for i in range(len(sequence)):
        filter_parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")

    current = "a0"
    for i in range(1, len(sequence)):
        label = f"x{i}" if i < len(sequence) - 1 else "joined"
        filter_parts.append(
            f"[{current}][a{i}]acrossfade=d={crossfade:.3f}:curve1=tri:curve2=tri[{label}]"
        )
        current = label

    fade_start = max(0.0, target - crossfade)
    filter_parts.append(
        f"[{current}]atrim=duration={target:.3f},"
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
