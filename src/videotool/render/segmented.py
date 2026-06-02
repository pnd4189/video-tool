from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from videotool.core.timeline import Timeline, TimelineOutput, TimelineScene
from videotool.render.audio_graph import audio_settings, build_audio_graph, build_audio_output_graph
from videotool.render.commands import CommandPlan
from videotool.render.overlay_graph import build_video_overlay, needs_video_overlay, particle_input_args
from videotool.render.profiles import RenderProfile
from videotool.render.video_filters import codec_args, is_image, metadata_args, scene_filter

# Cap the per-clip fade so short scenes are not all fade. Hard cuts at clip seams
# (concat demuxer) are softened by this in/out fade; true N-way crossfade is deferred.
MAX_CLIP_FADE_SECONDS = 0.5


@dataclass(frozen=True)
class SegmentedPlan:
    scene_commands: list[CommandPlan]
    concat_list_path: Path
    concat_list_text: str
    mux_command: list[str]
    output_path: Path
    preset: str


def build_segmented_render(
    timeline: Timeline,
    profile: RenderProfile,
    output: TimelineOutput,
    *,
    clips_dir: Path,
    concat_list_path: Path,
) -> SegmentedPlan:
    """Plan a resumable render: one self-contained clip per scene, joined by the concat
    demuxer with audio muxed in a final pass.

    Every clip shares identical codec/scale/fps/pixel-format so ``-c:v copy`` concatenation
    is valid. The final mux reuses the shared audio graph (dB gains / duck / loudnorm).
    """
    scene_commands = [
        _build_scene_clip(index, scene, profile, output, clips_dir)
        for index, scene in enumerate(timeline.scenes)
    ]
    concat_list_text = "".join(
        f"file '{plan.output_path}'\n" for plan in scene_commands
    )
    mux_command = _build_mux_command(timeline, profile, output, concat_list_path)
    return SegmentedPlan(
        scene_commands=scene_commands,
        concat_list_path=concat_list_path,
        concat_list_text=concat_list_text,
        mux_command=mux_command,
        output_path=output.output_path,
        preset=output.preset.name,
    )


def _build_scene_clip(
    index: int,
    scene: TimelineScene,
    profile: RenderProfile,
    output: TimelineOutput,
    clips_dir: Path,
) -> CommandPlan:
    clip_path = (clips_dir / f"scene-{index:04}.mp4").resolve()
    command = ["ffmpeg", "-y"]
    if is_image(scene.media_path):
        command.extend(["-loop", "1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])
    else:
        command.extend(["-stream_loop", "-1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])
    fade = min(MAX_CLIP_FADE_SECONDS, scene.duration / 4)
    fade_out_start = max(0.0, scene.duration - fade)
    graph = (
        f"{scene_filter(0, scene, output, 'vbase')};"
        f"[vbase]fade=t=in:st=0:d={fade:.3f},"
        f"fade=t=out:st={fade_out_start:.3f}:d={fade:.3f}[v]"
    )
    command.extend(["-filter_complex", graph, "-map", "[v]", "-an"])
    command.extend(codec_args(profile))
    command.append(str(clip_path))
    return CommandPlan(command=command, output_path=clip_path, preset=output.preset.name)


def _build_mux_command(timeline: Timeline, profile: RenderProfile, output: TimelineOutput, concat_list_path: Path) -> list[str]:
    # Concat input = 0, voice = 1, music = 2 (when present).
    command = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_path)]
    command.extend(["-i", str(timeline.voice_path)])
    if timeline.music_path:
        command.extend(["-stream_loop", "-1", "-i", str(timeline.music_path)])
    particle_index = _append_particle_input(command, timeline, output)
    if needs_video_overlay(timeline):
        filters, voice_audio, voice_visual = _voice_labels_for_complex(timeline)
        filters.append(
            build_video_overlay(
                "0:v:0", "v", timeline, output,
                particle_input_idx=particle_index, audio_label=voice_visual,
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
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
    ])
    command.append(str(output.output_path))
    return command


def _append_particle_input(command: list[str], timeline: Timeline, output: TimelineOutput) -> int | None:
    if not timeline.enhance_particles:
        return None
    index = sum(1 for arg in command if arg == "-i")
    command.extend(particle_input_args(timeline, output))
    return index


def _voice_labels_for_complex(timeline: Timeline) -> tuple[list[str], str, str | None]:
    if not timeline.enhance_visualizer:
        return [], "1:a", None
    return ["[1:a]asplit=2[voiceaudio][voiceviz]"], "voiceaudio", "voiceviz"
