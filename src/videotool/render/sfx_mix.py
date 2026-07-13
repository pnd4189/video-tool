from __future__ import annotations

import os
import subprocess
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError

SUBPROCESS_TIMEOUT_SECONDS = 1800
LIMITER_CEILING = 0.95


def build_sfx_mix_command(
    video_in: Path,
    cues: list[tuple[Path, float, float]],
    video_out: Path,
    *,
    intro_offset: float = 0.0,
    audio_bitrate: str = "256k",
) -> list[str] | None:
    """Build an ffmpeg command that mixes one-shot SFX onto an already-rendered mp4, remuxing
    audio only (`-c:v copy` — the video is never re-encoded). Each cue is a (file, time, gain_db):
    the clip is delayed to `time + intro_offset` and mixed UN-ducked over the existing audio, then
    a limiter guards against summing clips clipping. `duration=first` keeps the output the length of
    the source audio so a cue past the end is trimmed. Returns None when there are no cues.

    `cues` times are narration-aligned; `intro_offset` (the intro-CTA length) shifts them onto the
    composed timeline so an SFX lands on the right frame of the final video."""
    if not cues:
        return None
    inputs: list[str] = ["-i", str(video_in)]
    for path, _, _ in cues:
        inputs.extend(["-i", str(path)])

    filter_parts: list[str] = []
    labels: list[str] = []
    for index, (_, time, gain_db) in enumerate(cues):
        delay_ms = max(0, round((time + intro_offset) * 1000))
        label = f"s{index}"
        # input 0 is the video; SFX inputs start at 1.
        filter_parts.append(f"[{index + 1}:a]volume={gain_db:g}dB,adelay={delay_ms}:all=1[{label}]")
        labels.append(label)
    mix_inputs = "".join(f"[{label}]" for label in labels)
    filter_parts.append(
        f"[0:a]{mix_inputs}amix=inputs={len(cues) + 1}:normalize=0:duration=first[mix]"
    )
    filter_parts.append(f"[mix]alimiter=limit={LIMITER_CEILING}[a]")

    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", "0:v", "-c:v", "copy",
        "-map", "[a]", "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(video_out),
    ]


def mix_sfx_onto(
    source: Path,
    dest: Path,
    cues: list[tuple[Path, float, float]],
    *,
    intro_offset: float = 0.0,
    audio_bitrate: str = "256k",
) -> bool:
    """Mix SFX cues from `source` and write the result to `dest`. Renders to a temp file first
    and only `os.replace`s onto `dest` on success, so a failed ffmpeg run never destroys an
    existing `dest`. Callers pass a preserved pre-SFX master as `source` so re-runs stay
    idempotent (no double-mix / generational re-encode). Returns True when SFX were mixed,
    False when there were no cues (dest untouched)."""
    tmp = dest.with_name(f"{dest.stem}.sfx-tmp{dest.suffix}")
    command = build_sfx_mix_command(source, cues, tmp, intro_offset=intro_offset, audio_bitrate=audio_bitrate)
    if command is None:
        return False
    try:
        _run(command)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return True


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace", check=False, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError("SFX mix timed out.") from exc
    if result.returncode != 0:
        raise RenderError(f"FFmpeg failed mixing SFX (exit {result.returncode}):\n{result.stderr}")
