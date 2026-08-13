from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from videotool.core.media_probe import probe_media
from videotool.core.timeline import Timeline, TimelineOutput, TimelineScene
from videotool.render.audio_graph import audio_settings, build_audio_graph, build_audio_output_graph
from videotool.render.commands import CommandPlan
from videotool.render.overlay_graph import (
    build_scene_atmosphere,
    build_video_overlay,
    needs_video_overlay,
    particle_input_args,
    particle_overlay_path,
)
from videotool.render.profiles import RenderProfile
from videotool.render.video_filters import codec_args, is_image, metadata_args, scene_filter

# Cap the per-clip fade so short scenes are not all fade. Hard cuts at clip seams
# (concat demuxer) are softened by this in/out fade; true N-way crossfade is deferred.
MAX_CLIP_FADE_SECONDS = 0.5


@dataclass(frozen=True)
class ReconcileSpec:
    """Everything needed to re-render one scene clip with an adjusted duration, so the
    concatenated scene block can be reconciled to its design total after render.

    Each scene clip comes out of ffmpeg a fraction of a frame short of its allocated duration
    (``floor(duration*fps)/fps``). Across hundreds of scenes that shortfall accumulates into
    seconds — enough that ``-shortest`` then carves the outro CTA off the end of the video
    (see the Chap 34 outro-truncation incident). The executor measures the real clip total
    and, if it is short, re-renders this clip (the LAST NARRATION scene — not the outro card,
    so the outro stays aligned with its voice) with the deficit added back."""

    index: int
    scene: TimelineScene
    profile: RenderProfile
    output: TimelineOutput
    clips_dir: Path
    atmosphere: tuple[Path, float] | None = None
    atmosphere_seek: float | None = None

    def clip_command(self, duration: float) -> CommandPlan:
        scene = replace(self.scene, duration=duration)
        return _build_scene_clip(
            self.index, scene, self.profile, self.output, self.clips_dir,
            self.atmosphere, self.atmosphere_seek,
        )


@dataclass(frozen=True)
class SegmentedPlan:
    scene_commands: list[CommandPlan]
    concat_list_path: Path
    concat_list_text: str
    mux_command: list[str]
    output_path: Path
    preset: str
    # Design sum of scene durations (what the concatenated clips must total so the video
    # matches the composed audio and ``-shortest`` cuts nothing). 0.0 when no reconciliation.
    scenes_total_duration: float = 0.0
    # Re-render target for the duration reconcile (the last narration scene); None disables it.
    reconcile: ReconcileSpec | None = None


def build_segmented_render(
    timeline: Timeline,
    profile: RenderProfile,
    output: TimelineOutput,
    *,
    clips_dir: Path,
    concat_list_path: Path,
    reconcile_scene_index: int | None = None,
) -> SegmentedPlan:
    """Plan a resumable render: one self-contained clip per scene, joined by the concat
    demuxer with audio muxed in a final pass.

    Every clip shares identical codec/scale/fps/pixel-format so ``-c:v copy`` concatenation
    is valid. The final mux reuses the shared audio graph (dB gains / duck / loudnorm).

    ``reconcile_scene_index`` nominates the scene whose clip the executor may re-render to
    absorb the per-clip duration shortfall (frame rounding accumulates across many scenes).
    It should be the LAST NARRATION scene — the outro CTA card must keep its place so the
    outro voice stays aligned. Defaults to the last scene when unspecified (no-outro case).
    """
    atmosphere = _scene_atmosphere(timeline)
    scene_commands = []
    reconcile: ReconcileSpec | None = None
    elapsed = 0.0
    target = len(timeline.scenes) - 1 if reconcile_scene_index is None else reconcile_scene_index
    for index, scene in enumerate(timeline.scenes):
        seek = elapsed % atmosphere[1] if atmosphere else None
        scene_commands.append(
            _build_scene_clip(index, scene, profile, output, clips_dir, atmosphere, seek)
        )
        if index == target:
            reconcile = ReconcileSpec(index, scene, profile, output, clips_dir, atmosphere, seek)
        elapsed += scene.duration
    concat_list_text = "".join(
        f"file '{plan.output_path}'\n" for plan in scene_commands
    )
    mux_command = _build_mux_command(
        timeline, profile, output, concat_list_path, bakes_atmosphere=atmosphere is not None
    )
    return SegmentedPlan(
        scene_commands=scene_commands,
        concat_list_path=concat_list_path,
        concat_list_text=concat_list_text,
        mux_command=mux_command,
        output_path=output.output_path,
        preset=output.preset.name,
        scenes_total_duration=elapsed,
        reconcile=reconcile,
    )


def _build_scene_clip(
    index: int,
    scene: TimelineScene,
    profile: RenderProfile,
    output: TimelineOutput,
    clips_dir: Path,
    atmosphere: tuple[Path, float] | None = None,
    atmosphere_seek: float | None = None,
) -> CommandPlan:
    clip_path = (clips_dir / f"scene-{index:04}.mp4").resolve()
    command = ["ffmpeg", "-y"]
    if is_image(scene.media_path):
        command.extend(["-loop", "1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])
    else:
        command.extend(["-stream_loop", "-1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])
    fade = min(MAX_CLIP_FADE_SECONDS, scene.duration / 4)
    fade_out_start = max(0.0, scene.duration - fade)
    faded = "v" if atmosphere is None else "vfade"
    graph = (
        f"{scene_filter(0, scene, output, 'vbase')};"
        f"[vbase]fade=t=in:st=0:d={fade:.3f},"
        f"fade=t=out:st={fade_out_start:.3f}:d={fade:.3f}[{faded}]"
    )
    if atmosphere is not None:
        # Seek the overlay to where this scene sits on the timeline, so the loop reads as one
        # continuous effect instead of restarting at every cut.
        command.extend(["-stream_loop", "-1", "-ss", f"{atmosphere_seek or 0.0:.3f}", "-i", str(atmosphere[0])])
        graph += ";" + build_scene_atmosphere(faded, "v", output, 1)
    command.extend(["-filter_complex", graph, "-map", "[v]", "-an"])
    command.extend(codec_args(profile))
    command.append(str(clip_path))
    return CommandPlan(command=command, output_path=clip_path, preset=output.preset.name)


def _scene_atmosphere(timeline: Timeline) -> tuple[Path, float] | None:
    """Overlay clip + its duration when the atmosphere blend is baked per scene.

    Only the BYO atmosphere clip moves into the scene pass — it is the expensive filter (full-res
    RGB round-trip) and the one that made the single-threaded final mux dominate wall time. The
    bundled `particles` overlay stays in the mux; it is cheap and shares no code path.
    """
    if not timeline.enhance_atmosphere or timeline.enhance_particles:
        return None
    path = particle_overlay_path(timeline)
    duration = probe_media(path).duration
    if duration <= 0:
        return None
    return path, duration


def _build_mux_command(
    timeline: Timeline,
    profile: RenderProfile,
    output: TimelineOutput,
    concat_list_path: Path,
    *,
    bakes_atmosphere: bool = False,
) -> list[str]:
    # Concat input = 0, voice = 1, music = 2 (when present).
    command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_path)]
    command.extend(["-i", str(timeline.voice_path)])
    if timeline.music_path:
        command.extend(["-stream_loop", "-1", "-i", str(timeline.music_path)])
    # The atmosphere blend is already baked into the scene clips; only the cheap `particles`
    # overlay still needs its input here.
    particle_index = _append_particle_input(command, timeline, output, skip_atmosphere=bakes_atmosphere)
    if _needs_mux_overlay(timeline, bakes_atmosphere):
        filters, voice_audio, voice_visual = _voice_labels_for_complex(timeline)
        filters.append(
            build_video_overlay(
                "0:v:0", "v", timeline, output,
                particle_input_idx=particle_index, audio_label=voice_visual,
                include_atmosphere=not bakes_atmosphere,
            )
        )
        filters.append(
            build_audio_output_graph(
                voice_audio,
                "2:a" if timeline.music_path else None,
                **audio_settings(timeline),
            )
        )
        command.extend(["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[aout]"])
        command.extend(codec_args(profile))
    elif timeline.music_path:
        audio_graph = build_audio_graph("1:a", "2:a", **audio_settings(timeline))
        command.extend(["-filter_complex", audio_graph, "-map", "0:v:0", "-map", "[aout]"])
        command.extend(["-c:v", "copy"])
    else:
        af = build_audio_graph("1:a", None, **audio_settings(timeline))
        command.extend(["-map", "0:v:0", "-map", "1:a:0", "-af", af])
        command.extend(["-c:v", "copy"])
    command.extend(metadata_args(timeline))
    command.extend([
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
    ])
    command.append(str(output.output_path))
    return command


def _needs_mux_overlay(timeline: Timeline, bakes_atmosphere: bool) -> bool:
    """Whether the mux still has filter work once the atmosphere is baked per scene. When it is
    the only effect, the mux drops to a `-c:v copy` remux — the cheapest path there is."""
    if not bakes_atmosphere:
        return needs_video_overlay(timeline)
    return needs_video_overlay(replace(timeline, enhance_atmosphere=False))


def _append_particle_input(
    command: list[str], timeline: Timeline, output: TimelineOutput, *, skip_atmosphere: bool = False
) -> int | None:
    # One overlay input clip serves either the dust particles or the atmosphere screen-blend.
    if skip_atmosphere and not timeline.enhance_particles:
        return None
    if not (timeline.enhance_particles or timeline.enhance_atmosphere):
        return None
    index = sum(1 for arg in command if arg == "-i")
    command.extend(particle_input_args(timeline, output))
    return index


def _voice_labels_for_complex(timeline: Timeline) -> tuple[list[str], str, str | None]:
    if not timeline.enhance_visualizer:
        return [], "1:a", None
    return ["[1:a]asplit=2[voiceaudio][voiceviz]"], "voiceaudio", "voiceviz"
