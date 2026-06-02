from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from videotool.core.timeline import Timeline, TimelineOutput, TimelineScene
from videotool.render.audio_graph import audio_settings, build_audio_graph, build_audio_output_graph
from videotool.render.overlay_graph import (
    build_video_overlay,
    caption_filter,
    needs_video_overlay,
    particle_input_args,
)
from videotool.render.profiles import RenderProfile
from videotool.render.video_filters import codec_args, is_image, metadata_args, scene_filter


@dataclass(frozen=True)
class CommandPlan:
    command: list[str]
    output_path: Path
    preset: str


def build_ffmpeg_command(timeline: Timeline, profile: RenderProfile, output: TimelineOutput) -> CommandPlan:
    _reject_unsupported_profile(profile)
    if timeline.scenes:
        return _build_storyboard_command(timeline, profile, output)
    media_inputs = sorted(
        [path for path in timeline.media_dir.iterdir() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".mp4", ".mov"}]
    ) if timeline.media_dir.exists() else []
    background = media_inputs[0] if media_inputs else None
    command = ["ffmpeg", "-y"]
    if background and background.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        command.extend(["-loop", "1", "-i", str(background)])
    elif background:
        command.extend(["-stream_loop", "-1", "-i", str(background)])
    else:
        command.extend(["-f", "lavfi", "-i", f"color=c=black:s={output.preset.width}x{output.preset.height}:r={output.preset.fps}"])
    command.extend(["-i", str(timeline.voice_path)])
    if timeline.music_path:
        command.extend(["-stream_loop", "-1", "-i", str(timeline.music_path)])
    particle_index = _append_particle_input(command, timeline, output)
    duration_args = ["-shortest"]
    if timeline.duration:
        duration_args = ["-t", f"{timeline.duration:.3f}"]
    base_filter = (
        f"scale={output.preset.width}:{output.preset.height}:force_original_aspect_ratio=increase,"
        f"crop={output.preset.width}:{output.preset.height},setsar=1,fps={output.preset.fps},format=yuv420p"
    )
    if needs_video_overlay(timeline):
        filters, voice_audio, voice_visual = _voice_labels_for_complex(timeline, 1)
        # Manual srt-and-burn (no enhance) still burns here; enhance subtitles burn inside the overlay.
        caption = caption_filter(timeline, output)
        base = f"{base_filter},{caption}" if caption and not timeline.enhance_subtitles else base_filter
        filters.append(f"[0:v]{base}[vbase]")
        filters.append(
            build_video_overlay(
                "vbase", "vfull", timeline, output,
                particle_input_idx=particle_index, audio_label=voice_visual,
            )
        )
        filters.append(build_audio_output_graph(voice_audio, "2:a" if timeline.music_path else None, **audio_settings(timeline)))
        command.extend(["-filter_complex", ";".join(part for part in filters if part), "-map", "[vfull]", "-map", "[aout]"])
    elif timeline.music_path:
        caption = caption_filter(timeline, output)
        video_filter = f"{base_filter},{caption}" if caption else base_filter
        command.extend(["-vf", video_filter])
        audio_graph = build_audio_graph("1:a", "2:a", **audio_settings(timeline))
        command.extend(["-filter_complex", audio_graph, "-map", "0:v:0", "-map", "[aout]"])
    else:
        caption = caption_filter(timeline, output)
        video_filter = f"{base_filter},{caption}" if caption else base_filter
        command.extend(["-vf", video_filter])
        af = build_audio_graph("1:a", None, **audio_settings(timeline))
        command.extend(["-map", "0:v:0", "-map", "1:a:0", "-af", af])
    command.extend(codec_args(profile))
    command.extend(metadata_args(timeline))
    command.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"])
    command.extend(duration_args)
    command.append(str(output.output_path))
    return CommandPlan(command=command, output_path=output.output_path, preset=output.preset.name)


def _build_storyboard_command(timeline: Timeline, profile: RenderProfile, output: TimelineOutput) -> CommandPlan:
    command = ["ffmpeg", "-y"]
    for scene in timeline.scenes:
        if is_image(scene.media_path):
            command.extend(["-loop", "1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])
        else:
            command.extend(["-stream_loop", "-1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])

    voice_index = len(timeline.scenes)
    command.extend(["-i", str(timeline.voice_path)])
    music_index = voice_index + 1
    if timeline.music_path:
        command.extend(["-stream_loop", "-1", "-i", str(timeline.music_path)])
    particle_index = _append_particle_input(command, timeline, output)

    filters: list[str] = []
    scene_labels: list[str] = []
    for index, scene in enumerate(timeline.scenes):
        label = f"v{index}"
        scene_labels.append(label)
        filters.append(scene_filter(index, scene, output, label))
    video_label = _join_scene_filters(filters, scene_labels, timeline.scenes)
    caption = caption_filter(timeline, output)
    if caption and not timeline.enhance_subtitles:
        filters.append(f"[{video_label}]{caption},format=yuv420p[vcaption]")
        video_label = "vcaption"
    if needs_video_overlay(timeline):
        audio_filters, voice_audio, voice_visual = _voice_labels_for_complex(timeline, voice_index)
        filters.extend(audio_filters)
        filters.append(
            build_video_overlay(
                video_label, "vfull", timeline, output,
                particle_input_idx=particle_index, audio_label=voice_visual,
            )
        )
        filters.append(
            build_audio_output_graph(
                voice_audio,
                f"{music_index}:a" if timeline.music_path else None,
                **audio_settings(timeline),
            )
        )
        command.extend(["-filter_complex", ";".join(filters), "-map", "[vfull]", "-map", "[aout]"])
    elif timeline.music_path:
        filters.append(build_audio_graph(f"{voice_index}:a", f"{music_index}:a", **audio_settings(timeline)))
        command.extend(["-filter_complex", ";".join(filters), "-map", f"[{video_label}]", "-map", "[aout]"])
    else:
        command.extend(["-filter_complex", ";".join(filters), "-map", f"[{video_label}]"])
        af = build_audio_graph(f"{voice_index}:a", None, **audio_settings(timeline))
        command.extend(["-map", f"{voice_index}:a:0", "-af", af])

    command.extend(codec_args(profile))
    command.extend(metadata_args(timeline))
    command.extend([
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        # Storyboards concat many segments; raise muxer queue to handle long timelines.
        "-max_muxing_queue_size", "9999",
        "-shortest",
    ])
    command.append(str(output.output_path))
    return CommandPlan(command=command, output_path=output.output_path, preset=output.preset.name)


def _reject_unsupported_profile(profile: RenderProfile) -> None:
    if not profile.encoder.startswith("libx264"):
        # VAAPI/AV1/HEVC profiles need -vaapi_device, -hwaccel and hwupload filter chain
        # that this builder does not emit yet. Fail clearly instead of producing a broken command.
        raise NotImplementedError(
            f"Encoder '{profile.encoder}' is not wired in this build. "
            "Use 'libx264-balanced' or 'libx264-fast'."
        )


def _join_scene_filters(filters: list[str], labels: list[str], scenes: list[TimelineScene]) -> str:
    if len(labels) == 1:
        filters.append(f"[{labels[0]}]format=yuv420p[vout]")
        return "vout"
    current = labels[0]
    accumulated = scenes[0].duration
    for index, label in enumerate(labels[1:], start=1):
        output_label = f"vx{index}"
        transition = scenes[index].transition
        if transition == "cut":
            filters.append(f"[{current}][{label}]concat=n=2:v=1:a=0[{output_label}]")
            accumulated += scenes[index].duration
        else:
            duration = min(0.5, scenes[index - 1].duration / 3, scenes[index].duration / 3)
            offset = max(0.0, accumulated - duration)
            filters.append(
                f"[{current}][{label}]xfade=transition={_xfade_name(transition)}:"
                f"duration={duration:.3f}:offset={offset:.3f}[{output_label}]"
            )
            accumulated += scenes[index].duration - duration
        current = output_label
    filters.append(f"[{current}]format=yuv420p[vout]")
    return "vout"


def _xfade_name(transition: str) -> str:
    if transition == "dip-to-black":
        return "fadeblack"
    return "fade"


def _append_particle_input(command: list[str], timeline: Timeline, output: TimelineOutput) -> int | None:
    if not timeline.enhance_particles:
        return None
    index = _next_input_index(command)
    command.extend(particle_input_args(timeline, output))
    return index


def _next_input_index(command: list[str]) -> int:
    return sum(1 for arg in command if arg == "-i")


def _voice_labels_for_complex(timeline: Timeline, voice_index: int) -> tuple[list[str], str, str | None]:
    if not timeline.enhance_visualizer:
        return [], f"{voice_index}:a", None
    return [f"[{voice_index}:a]asplit=2[voiceaudio][voiceviz]"], "voiceaudio", "voiceviz"
