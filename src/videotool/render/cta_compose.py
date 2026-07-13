from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError
from videotool.core.media_probe import probe_media

SUBPROCESS_TIMEOUT_SECONDS = 1800
# Synthetic first chapter covering the intro CTA. YouTube requires the first chapter marker
# to sit at 00:00, so narration chapters are shifted and this label anchors the start.
INTRO_CHAPTER_TITLE = "Giới thiệu"


@dataclass(frozen=True)
class ComposedVoice:
    path: Path
    intro_seconds: float
    outro_seconds: float


def compose_voice(
    narration: Path,
    output: Path,
    *,
    intro: Path | None,
    outro: Path | None,
) -> ComposedVoice:
    """Concatenate optional intro/outro CTA clips around the narration into one track.

    Segments are normalized to 48 kHz stereo before concatenation so clips recorded at
    different rates/layouts (e.g. a 44.1 kHz mono ElevenLabs CTA) join cleanly. Returns the
    composed FLAC plus the intro/outro durations used to offset chapters/subtitles and to
    size the matching title-card scenes.
    """
    segments: list[Path] = []
    intro_seconds = 0.0
    outro_seconds = 0.0
    if intro is not None:
        intro_seconds = _duration(intro)
        segments.append(intro)
    segments.append(narration)
    if outro is not None:
        outro_seconds = _duration(outro)
        segments.append(outro)
    output.parent.mkdir(parents=True, exist_ok=True)
    _run(_build_concat_command(segments, output))
    return ComposedVoice(path=output, intro_seconds=intro_seconds, outro_seconds=outro_seconds)


def shift_srt(text: str, offset_seconds: float) -> str:
    """Shift every SRT cue timestamp by ``offset_seconds`` (used when an intro CTA pushes the
    narration later in the final video)."""
    if offset_seconds <= 0:
        return text

    def _shift(match: re.Match[str]) -> str:
        hours, minutes, seconds, millis = (int(part) for part in match.groups())
        total = hours * 3600 + minutes * 60 + seconds + millis / 1000 + offset_seconds
        return _format_srt_timestamp(total)

    return _SRT_TIMESTAMP.sub(_shift, text)


def offset_chapters(
    chapters: list[tuple[float, str]],
    intro_seconds: float,
    intro_title: str = INTRO_CHAPTER_TITLE,
) -> list[tuple[float, str]]:
    """Shift narration chapters by the intro CTA duration and prepend a 00:00 intro chapter
    so YouTube still recognises the chapter list (first marker must be 00:00)."""
    if intro_seconds <= 0:
        return chapters
    shifted = [(start + intro_seconds, title) for start, title in chapters]
    return [(0.0, intro_title), *shifted]


_SRT_TIMESTAMP = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _format_srt_timestamp(total_seconds: float) -> str:
    millis = int(round(total_seconds * 1000))
    hours, millis = divmod(millis, 3600 * 1000)
    minutes, millis = divmod(millis, 60 * 1000)
    seconds, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _duration(path: Path) -> float:
    duration = probe_media(path).duration or 0.0
    if duration <= 0:
        raise RenderError(f"compose_voice: could not probe CTA duration: {path}")
    return duration


def _build_concat_command(segments: list[Path], output: Path) -> list[str]:
    inputs: list[str] = []
    for segment in segments:
        inputs.extend(["-i", str(segment)])
    parts = [
        f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]"
        for i in range(len(segments))
    ]
    chain = "".join(f"[a{i}]" for i in range(len(segments)))
    parts.append(f"{chain}concat=n={len(segments)}:v=0:a=1[out]")
    return [
        "ffmpeg", "-y", "-hide_banner", "-nostats",
        *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[out]",
        "-c:a", "flac", "-compression_level", "5",
        str(output),
    ]


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace", check=False, timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError("CTA voice composition timed out.") from exc
    if result.returncode != 0:
        raise RenderError(
            f"FFmpeg failed composing CTA voice (exit {result.returncode}):\n{result.stderr}"
        )
