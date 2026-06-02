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

    if timeline.enhance_progress_bar:
        duration = _duration(timeline)
        current = _append(
            filters,
            current,
            f"drawbox=x=0:y=ih-10:w=iw*t/{duration:.3f}:h=10:color=white@0.65:t=fill",
            "vprogress",
        )

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
            timeline.enhance_progress_bar,
            timeline.enhance_visualizer,
        )
    )


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


def _duration(timeline: Timeline) -> float:
    if timeline.duration and timeline.duration > 0:
        return timeline.duration
    scene_duration = sum(scene.duration for scene in timeline.scenes)
    return scene_duration if scene_duration > 0 else 1.0


def _escape_filter_value(path: Path) -> str:
    text = str(path)
    text = text.replace("\\", "\\\\")
    for ch in (":", ",", "'", "[", "]", ";"):
        text = text.replace(ch, "\\" + ch)
    return text
