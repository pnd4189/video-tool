"""Timeline overlays drawn inside each scene clip instead of over the concatenated video.

The segmented render joins scene clips with the concat demuxer. Anything drawn over the whole video
(burned subtitles, mood filters, the waveform) makes the mux decode and re-encode every frame a second
time; on a 4-core box that second encode cost ~1.9 h per hour of video (Chap 71, 2026-10-12). With
`render.bake_overlays` each clip runs the same `build_video_overlay` chain on its own slice of the
timeline, and the mux drops to its stream-copy branch.

Two rules keep the slices seamless:
- every clip has an exact frame count (`-frames:v`) taken from the rounded cumulative timeline, so clip i
  starts exactly at `start_frame / fps` and nothing drifts;
- the chain runs on timeline time: `setpts` moves the clip to its timeline start before the overlays
  (libass and time-based filters read the frame time) and back to zero after, and the waveform reads its
  own slice of the voice, moved the same way.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from videotool.core.timeline import Timeline, TimelineOutput, TimelineScene
from videotool.render.overlay_graph import build_video_overlay, needs_video_overlay


@dataclass(frozen=True)
class BakedScene:
    """One scene's slice of the timeline. ``scene.duration`` carries one frame of headroom so the scene
    filters always yield ``frames`` frames; ``-frames:v`` then cuts the clip to exactly that many."""

    scene: TimelineScene
    start: float
    frames: int


def wants_baked_overlays(timeline: Timeline) -> bool:
    """Bake only when something besides the per-scene atmosphere is drawn over the video, and never with
    the bundled `particles` clip, which loops once across the whole video and so stays in the mux."""
    if timeline.enhance_particles:
        return False
    return needs_video_overlay(replace(timeline, enhance_atmosphere=False))


def frame_exact_scenes(scenes: list[TimelineScene], fps: int) -> list[BakedScene]:
    baked: list[BakedScene] = []
    elapsed = 0.0
    start_frame = 0
    for scene in scenes:
        elapsed += scene.duration
        frames = max(1, round(elapsed * fps) - start_frame)
        baked.append(BakedScene(replace(scene, duration=(frames + 1) / fps), start_frame / fps, frames))
        start_frame += frames
    return baked


def voice_input_args(timeline: Timeline, baked: BakedScene, fps: int) -> list[str]:
    """The slice of the voice the waveform draws for this clip; nothing when the waveform is off."""
    if not timeline.enhance_visualizer:
        return []
    return ["-ss", f"{baked.start:.6f}", "-t", f"{(baked.frames + 1) / fps:.6f}", "-i", str(timeline.voice_path)]


def baked_overlay_graph(
    label_in: str,
    label_out: str,
    timeline: Timeline,
    output: TimelineOutput,
    baked: BakedScene,
    voice_input_idx: int | None,
) -> str:
    shift = f"floor({baked.start:.6f}/TB+0.5)"
    filters = [f"[{label_in}]setpts=PTS+{shift}[vtimeline]"]
    audio_label = None
    if voice_input_idx is not None:
        filters.append(f"[{voice_input_idx}:a]asetpts=PTS+{shift}[vtimeline_voice]")
        audio_label = "vtimeline_voice"
    filters.append(
        build_video_overlay(
            "vtimeline", "vtimeline_out", timeline, output,
            particle_input_idx=None, audio_label=audio_label, include_atmosphere=False,
        )
    )
    filters.append(f"[vtimeline_out]setpts=PTS-STARTPTS[{label_out}]")
    return ";".join(filters)
