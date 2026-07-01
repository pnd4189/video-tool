from __future__ import annotations

import re
import subprocess
from pathlib import Path

from videotool.ai.subtitles import validate_srt
from videotool.core.errors import DependencyError
from videotool.core.media_probe import probe_media
from videotool.core.presets import get_preset
from videotool.package.reports import QualityCheck

ACCEPTED_VIDEO_CODECS = {"h264", "hevc", "av1"}
ACCEPTED_AUDIO_CODECS = {"aac"}
YT_LUFS_TARGET = -14.0
YT_LUFS_TOLERANCE = 1.5  # ±1.5 LU is the practical window before YouTube re-normalizes audibly.


def validate_youtube_video(path: Path, preset_name: str) -> list[QualityCheck]:
    if not path.exists():
        return [QualityCheck("video_exists", "fail", f"Missing video: {path}")]
    preset = get_preset(preset_name)
    metadata = probe_media(path)
    checks = [QualityCheck("video_exists", "pass", str(path))]
    checks.append(_check("resolution", metadata.width == preset.width and metadata.height == preset.height, f"{metadata.width}x{metadata.height}"))
    checks.append(_check("video_codec", metadata.video_codec in ACCEPTED_VIDEO_CODECS, str(metadata.video_codec)))
    checks.append(_check("audio_codec", metadata.audio_codec in ACCEPTED_AUDIO_CODECS, str(metadata.audio_codec)))
    checks.append(_check("sample_rate", metadata.sample_rate == 48000, str(metadata.sample_rate)))
    checks.append(_lufs_check(path))
    return checks


def validate_package(output_dir: Path, expected_videos: list[str] | None = None, require_srt: bool = True) -> list[QualityCheck]:
    checks: list[QualityCheck] = []
    expected_videos = expected_videos or ["youtube-16x9.mp4", "shorts-9x16.mp4"]
    for file_name in expected_videos:
        preset = file_name.removesuffix(".mp4")
        checks.extend(validate_youtube_video(output_dir / file_name, preset))
    srt = output_dir / "captions.srt"
    srt_errors = validate_srt(srt)
    status = "fail" if require_srt and srt_errors else "warning" if srt_errors else "pass"
    checks.append(QualityCheck("captions_srt", status, "; ".join(srt_errors) if srt_errors else str(srt)))
    checks.append(_check("license_report", (output_dir / "license-report.md").exists(), "license-report.md"))
    checks.append(_check("description", (output_dir / "description.txt").exists(), "description.txt"))
    # quality-report.json and package-manifest.json are produced by the packaging step AFTER
    # this validation runs (the report IS the serialized check list), so asserting them here
    # is circular and always fails at generation time. They are not YouTube quality gates.
    checks.append(_check("thumbnail", (output_dir / "thumbnail-1280x720.jpg").exists(), "thumbnail-1280x720.jpg"))
    log_dir = output_dir.parent / ".videotool" / "tmp" / "logs"
    checks.append(_check("render_log", any(log_dir.glob("*.log")) if log_dir.exists() else False, str(log_dir)))
    return checks


def measure_integrated_lufs(path: Path) -> float | None:
    """Run ffmpeg ebur128 once and return integrated LUFS, or None if measurement failed."""
    command = [
        "ffmpeg", "-nostats", "-hide_banner",
        "-i", str(path),
        "-af", "ebur128=peak=true",
        "-f", "null", "-",
    ]
    try:
        # errors="replace": ffmpeg copies input metadata (e.g. Latin-1 ID3 tags) into stderr,
        # so utf-8 decoding raw ffmpeg output can raise UnicodeDecodeError on non-utf-8 bytes.
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False, timeout=600)
    except FileNotFoundError as exc:
        raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc
    except subprocess.TimeoutExpired:
        return None
    return parse_integrated_lufs(result.stderr)


def parse_integrated_lufs(stderr: str) -> float | None:
    """Extract the integrated loudness from ebur128 output.

    ebur128 prints a running ``I: … LUFS`` per frame (the first readings are near-silent
    startup values) and a final ``Summary`` block with the true integrated loudness. Take the
    LAST match so long files report the summary value, not the startup reading.
    """
    matches = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", stderr)
    if not matches:
        return None
    return float(matches[-1])


def _lufs_check(path: Path) -> QualityCheck:
    try:
        measured = measure_integrated_lufs(path)
    except DependencyError as exc:
        return QualityCheck("loudness_lufs", "fail", str(exc))
    if measured is None:
        return QualityCheck("loudness_lufs", "warning", "could not measure integrated LUFS")
    delta = abs(measured - YT_LUFS_TARGET)
    status = "pass" if delta <= YT_LUFS_TOLERANCE else "warning"
    return QualityCheck("loudness_lufs", status, f"{measured:.2f} LUFS (target {YT_LUFS_TARGET:+.1f} ±{YT_LUFS_TOLERANCE})")


def write_description(
    title: str,
    license_report: Path,
    output_path: Path,
    description: str = "",
    chapters: list[tuple[float, str]] | None = None,
    tags: list[str] | None = None,
    cta: str = "",
) -> None:
    parts: list[str] = [title.strip()]
    if description:
        parts.append("")
        parts.append(description.strip())
    if chapters:
        parts.append("")
        parts.append("Chapters:")
        for start, chapter_title in chapters:
            parts.append(f"{_format_chapter_timestamp(start)} {chapter_title}")
    if cta:
        parts.append("")
        parts.append(cta.strip())
    parts.append("")
    parts.append(f"Credits and license metadata: see {license_report.name}.")
    if tags:
        parts.append("")
        parts.append(" ".join(f"#{tag.lstrip('#')}" for tag in tags))
    output_path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def format_chapters_block(chapters: list[tuple[float, str]]) -> str:
    """One ``MM:SS Title`` (or ``HH:MM:SS`` past an hour) line per chapter, in order."""
    return "\n".join(f"{_format_chapter_timestamp(start)} {title}" for start, title in chapters)


def render_description_template(
    template_text: str,
    *,
    chapters_block: str,
    recap_prev: str,
    summary: str,
) -> str:
    """Substitute the three channel placeholders. Literal replace (KISS); missing values
    collapse to empty so no ``{{...}}`` token is ever left in the output.

    A template with NONE of the placeholders is almost always the wrong file (e.g. a previous
    episode's finished description copied in by mistake) — that would publish stale chapters and
    the wrong recap, so warn loudly instead of silently emitting it verbatim.
    """
    placeholders = ("{{CHAPTERS}}", "{{RECAP_PREV}}", "{{SUMMARY}}")
    if not any(token in template_text for token in placeholders):
        from videotool.core.logging import console

        console.print(
            "[yellow]WARNING[/yellow] description template has none of "
            f"{', '.join(placeholders)} — emitting it verbatim. Chapters/recap/summary will "
            "NOT be injected; check inputs.description_template points at the template, not a "
            "finished description."
        )
    rendered = (
        template_text
        .replace("{{CHAPTERS}}", chapters_block)
        .replace("{{RECAP_PREV}}", recap_prev.strip())
        .replace("{{SUMMARY}}", summary.strip())
    )
    # Any {{...}} left over is an unsupported placeholder (typo or token we don't fill) that
    # would otherwise leak into the published description — flag it rather than ship it.
    leftover = re.findall(r"\{\{[^}]+\}\}", rendered)
    if leftover:
        from videotool.core.logging import console

        console.print(
            f"[yellow]WARNING[/yellow] description template has unfilled placeholder(s): "
            f"{', '.join(sorted(set(leftover)))}. Only {{{{CHAPTERS}}}}, {{{{RECAP_PREV}}}}, "
            "{{SUMMARY}} are supported — remove or fill the rest by hand."
        )
    return rendered


def _format_chapter_timestamp(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _check(name: str, passed: bool, message: str) -> QualityCheck:
    return QualityCheck(name, "pass" if passed else "fail", message)
