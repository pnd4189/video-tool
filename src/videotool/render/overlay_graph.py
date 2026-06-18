from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from videotool.core.timeline import Timeline, TimelineOutput


def build_video_overlay(
    label_in: str,
    label_out: str,
    timeline: Timeline,
    output: TimelineOutput,
    *,
    particle_input_idx: int | None,
    audio_label: str | None,
) -> str:
    filters: list[str] = []
    current = label_in

    caption = caption_filter(timeline, output) if timeline.enhance_subtitles else ""
    if caption:
        current = _append(filters, current, f"{caption},format=yuv420p", "vsub")

    # Group A: filter-only mood effects (no assets). Cheap, ride the single full-tier re-encode.
    grade = _color_grade_filter(timeline.enhance_color_grade)
    if grade:
        current = _append(filters, current, grade, "vgrade")
    if timeline.enhance_vignette:
        current = _append(filters, current, "vignette=PI/5", "vvig")
    if timeline.enhance_grain:
        current = _append(filters, current, "noise=alls=10:allf=t", "vgrain")
    if timeline.enhance_glow:
        # Self-contained bloom: blur a brightened copy and screen it back over the
        # original. The screen blend runs in RGB; blending in yuv420p would screen
        # the chroma planes too and tint the whole frame magenta.
        filters.append(
            f"[{current}]split=2[g0][g1];"
            f"[g1]gblur=sigma=14,eq=brightness=0.05,format=gbrp[g2];"
            f"[g0]format=gbrp[g0r];"
            f"[g0r][g2]blend=all_mode=screen,format=yuv420p[vglow]"
        )
        current = "vglow"
    if timeline.enhance_flicker:
        current = _append(
            filters, current,
            "eq=brightness='0.03*sin(2*PI*t*3)':eval=frame",
            "vflick",
        )

    if timeline.enhance_particles and particle_input_idx is not None:
        particle = "vparticle_src"
        filters.append(
            f"[{particle_input_idx}:v]scale={output.preset.width}:{output.preset.height}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={output.preset.width}:{output.preset.height},format=gray,"
            f"noise=alls=18:allf=t+u,format=rgba,colorchannelmixer=aa=0.10[{particle}]"
        )
        next_label = "vparticle"
        filters.append(f"[{current}][{particle}]overlay=shortest=1,format=yuv420p[{next_label}]")
        current = next_label
    elif timeline.enhance_atmosphere and particle_input_idx is not None:
        # BYO atmospheric clip (rain/snow/bokeh) blended screen at its own brightness.
        # Screen blend must run in RGB; blending in yuv420p screens the chroma
        # planes too and tints the whole frame magenta.
        atmo = "vatmo_src"
        atmo_base = "vatmo_base"
        filters.append(
            f"[{particle_input_idx}:v]scale={output.preset.width}:{output.preset.height}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={output.preset.width}:{output.preset.height},format=gbrp[{atmo}]"
        )
        next_label = "vatmo"
        filters.append(f"[{current}]format=gbrp[{atmo_base}]")
        filters.append(f"[{atmo_base}][{atmo}]blend=all_mode=screen:shortest=1,format=yuv420p[{next_label}]")
        current = next_label

    if timeline.enhance_visualizer and audio_label:
        wave = "vwaves"
        wave_height = max(72, output.preset.height // 10)
        filters.append(
            f"[{audio_label}]showwaves=s={output.preset.width}x{wave_height}:mode=line:"
            f"rate={output.preset.fps}:colors=white@0.65,format=rgba[{wave}]"
        )
        next_label = "vvisual"
        y = output.preset.height - wave_height - 24
        filters.append(f"[{current}][{wave}]overlay=x=0:y={y}:eof_action=pass,format=yuv420p[{next_label}]")
        current = next_label

    if current != label_out:
        filters.append(f"[{current}]format=yuv420p[{label_out}]")
    return ";".join(filters)


def needs_video_overlay(timeline: Timeline) -> bool:
    return any(
        (
            timeline.enhance_subtitles,
            timeline.enhance_particles,
            timeline.enhance_atmosphere,
            timeline.enhance_visualizer,
            timeline.enhance_vignette,
            timeline.enhance_grain,
            timeline.enhance_glow,
            timeline.enhance_flicker,
            bool(timeline.enhance_color_grade),
        )
    )


def _color_grade_filter(grade: str | None) -> str:
    if grade == "warm":
        return "colorbalance=rs=.06:gs=.02:bs=-.06"
    if grade == "cold":
        return "colorbalance=rs=-.06:gs=0:bs=.06"
    if grade == "neutral":
        return "eq=contrast=1.08:saturation=1.06"
    return ""


def caption_filter(timeline: Timeline, output: TimelineOutput) -> str:
    if timeline.caption_mode != "srt-and-burn":
        return ""
    srt_path = timeline.subtitle_path or timeline.root / "outputs" / "captions.srt"
    # PlayResX/Y pin the libass canvas to the real frame; without them libass assumes a tiny
    # default canvas and scales FontSize/MarginV up ~3-4x (subtitles balloon to fill the frame).
    width = output.preset.width
    height = output.preset.height
    # Lift captions above the showwaves band when the visualizer is on so the two never overlap.
    # Mirrors the showwaves geometry in build_video_overlay (wave_height + 24px offset).
    base_margin = 180 if height > width else 64
    margin_v = base_margin
    if timeline.enhance_visualizer:
        wave_height = max(72, height // 10)
        margin_v = max(base_margin, wave_height + 24 + 20)  # sit ~20px above the wave strip
    style = (
        f"PlayResX={width},PlayResY={height},"
        f"FontSize={output.preset.subtitle_font_size},Bold=1,"
        f"Outline=3,Shadow=1,Alignment=2,MarginV={margin_v}"
    )
    return f"subtitles=filename='{_escape_filter_value(srt_path)}':force_style='{style}'"


def particle_input_args(timeline: Timeline, output: TimelineOutput) -> list[str]:
    del output
    path = timeline.particle_overlay_path or _bundled_particle_overlay()
    return ["-stream_loop", "-1", "-i", str(path)]


def _bundled_particle_overlay() -> Path:
    return Path(str(files("videotool.assets.overlays").joinpath("dust.mp4")))


def _append(filters: list[str], label_in: str, body: str, label_out: str) -> str:
    filters.append(f"[{label_in}]{body}[{label_out}]")
    return label_out


def _escape_filter_value(path: Path) -> str:
    text = str(path)
    text = text.replace("\\", "\\\\")
    for ch in (":", ",", "'", "[", "]", ";"):
        text = text.replace(ch, "\\" + ch)
    return text
