from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from videotool.core.timeline import Timeline, TimelineOutput, TimelineScene
from videotool.render.profiles import RenderProfile

LOUDNORM_TARGET = "loudnorm=I=-14:TP=-1:LRA=11"
SIDECHAIN_PARAMS = "threshold=0.05:ratio=8:attack=5:release=400:makeup=2"


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
    duration_args = ["-shortest"]
    if timeline.duration:
        duration_args = ["-t", f"{timeline.duration:.3f}"]
    video_filter = (
        f"scale={output.preset.width}:{output.preset.height}:force_original_aspect_ratio=increase,"
        f"crop={output.preset.width}:{output.preset.height},setsar=1,fps={output.preset.fps},format=yuv420p"
    )
    caption_filter = _caption_filter(timeline, output)
    if caption_filter:
        video_filter = f"{video_filter},{caption_filter}"
    command.extend(["-vf", video_filter])
    if timeline.music_path:
        # voice index = 1, music index = 2. Sidechain compress ducks music using voice as key.
        # asplit duplicates the voice stream so we can both mix and use it as the sidechain key.
        audio_graph = (
            "[1:a]asplit=2[voice][voicekey];"
            f"[2:a]volume=0.5[musicpre];"
            f"[musicpre][voicekey]sidechaincompress={SIDECHAIN_PARAMS}[ducked];"
            f"[voice][ducked]amix=inputs=2:duration=first:normalize=0,{LOUDNORM_TARGET}[aout]"
        )
        command.extend(["-filter_complex", audio_graph, "-map", "0:v:0", "-map", "[aout]"])
    else:
        command.extend(["-map", "0:v:0", "-map", "1:a:0", "-af", LOUDNORM_TARGET])
    command.extend(_codec_args(profile))
    command.extend(_metadata_args(timeline))
    command.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"])
    command.extend(duration_args)
    command.append(str(output.output_path))
    return CommandPlan(command=command, output_path=output.output_path, preset=output.preset.name)


def _build_storyboard_command(timeline: Timeline, profile: RenderProfile, output: TimelineOutput) -> CommandPlan:
    command = ["ffmpeg", "-y"]
    for scene in timeline.scenes:
        if _is_image(scene.media_path):
            command.extend(["-loop", "1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])
        else:
            command.extend(["-stream_loop", "-1", "-t", f"{scene.duration:.3f}", "-i", str(scene.media_path)])

    voice_index = len(timeline.scenes)
    command.extend(["-i", str(timeline.voice_path)])
    music_index = voice_index + 1
    if timeline.music_path:
        command.extend(["-stream_loop", "-1", "-i", str(timeline.music_path)])

    filters: list[str] = []
    scene_labels: list[str] = []
    for index, scene in enumerate(timeline.scenes):
        label = f"v{index}"
        scene_labels.append(label)
        filters.append(_scene_filter(index, scene, output, label))
    video_label = _join_scene_filters(filters, scene_labels, timeline.scenes)
    caption_filter = _caption_filter(timeline, output)
    if caption_filter:
        filters.append(f"[{video_label}]{caption_filter},format=yuv420p[vcaption]")
        video_label = "vcaption"
    if timeline.music_path:
        filters.append(
            f"[{voice_index}:a]asplit=2[voice][voicekey];"
            f"[{music_index}:a]volume=0.5[musicpre];"
            f"[musicpre][voicekey]sidechaincompress={SIDECHAIN_PARAMS}[ducked];"
            f"[voice][ducked]amix=inputs=2:duration=first:normalize=0,{LOUDNORM_TARGET}[aout]"
        )
    command.extend(["-filter_complex", ";".join(filters), "-map", f"[{video_label}]"])
    if timeline.music_path:
        command.extend(["-map", "[aout]"])
    else:
        command.extend(["-map", f"{voice_index}:a:0", "-af", LOUDNORM_TARGET])

    command.extend(_codec_args(profile))
    command.extend(_metadata_args(timeline))
    command.extend([
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        # Storyboards concat many segments; raise muxer queue to handle long timelines.
        "-max_muxing_queue_size", "9999",
        "-shortest",
    ])
    command.append(str(output.output_path))
    return CommandPlan(command=command, output_path=output.output_path, preset=output.preset.name)


def _codec_args(profile: RenderProfile) -> list[str]:
    args = ["-c:v", profile.encoder]
    if profile.preset:
        args.extend(["-preset", profile.preset])
    if profile.crf is not None:
        args.extend(["-crf", str(profile.crf)])
    args.extend(["-pix_fmt", "yuv420p"])
    return args


def _metadata_args(timeline: Timeline) -> list[str]:
    args: list[str] = []
    if timeline.title:
        args.extend(["-metadata", f"title={timeline.title}"])
    if timeline.description:
        args.extend(["-metadata", f"description={timeline.description}"])
        args.extend(["-metadata", f"comment={timeline.description}"])
    if timeline.author:
        args.extend(["-metadata", f"artist={timeline.author}"])
    return args


def _reject_unsupported_profile(profile: RenderProfile) -> None:
    if not profile.encoder.startswith("libx264"):
        # VAAPI/AV1/HEVC profiles need -vaapi_device, -hwaccel and hwupload filter chain
        # that this builder does not emit yet. Fail clearly instead of producing a broken command.
        raise NotImplementedError(
            f"Encoder '{profile.encoder}' is not wired in this build. "
            "Use 'libx264-balanced' or 'libx264-fast'."
        )


def _scene_filter(index: int, scene: TimelineScene, output: TimelineOutput, label: str) -> str:
    width = output.preset.width
    height = output.preset.height
    fps = output.preset.fps
    if _is_image(scene.media_path):
        frames = max(1, int(scene.duration * fps))
        zoom, x_position, y_position = _motion_expr(scene.motion, frames)
        return (
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"zoompan=z='{zoom}':x='{x_position}':y='{y_position}':d={frames}:s={width}x{height}:fps={fps},"
            f"trim=duration={scene.duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[{label}]"
        )
    return (
        f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps},"
        f"trim=duration={scene.duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[{label}]"
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


def _motion_expr(motion: str, frames: int) -> tuple[str, str, str]:
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    if motion == "zoom-out":
        return f"max(1.0,1.12-0.12*on/{frames})", center_x, center_y
    if motion == "pan-left":
        return "1.12", f"(iw-iw/zoom)*(1-on/{frames})", center_y
    if motion == "pan-right":
        return "1.12", f"(iw-iw/zoom)*on/{frames}", center_y
    if motion == "pan-up":
        return "1.12", center_x, f"(ih-ih/zoom)*(1-on/{frames})"
    if motion == "pan-down":
        return "1.12", center_x, f"(ih-ih/zoom)*on/{frames}"
    return f"min(1.12,1.0+0.12*on/{frames})", center_x, center_y


def _xfade_name(transition: str) -> str:
    if transition == "dip-to-black":
        return "fadeblack"
    return "fade"


def _caption_filter(timeline: Timeline, output: TimelineOutput) -> str:
    if timeline.caption_mode != "srt-and-burn":
        return ""
    # Prefer a pre-staged safe-path SRT (set by services.run_render) to avoid filter-graph
    # escape pitfalls. Fall back to the canonical outputs/captions.srt for callers that
    # build a command directly (tests, dry-run).
    srt_path = timeline.subtitle_path or timeline.root / "outputs" / "captions.srt"
    alignment = 2  # bottom-center for 16:9
    margin_v = 64
    if output.preset.height > output.preset.width:
        # Shorts/vertical: lift captions higher so they are not cut by mobile UI overlays.
        alignment = 2
        margin_v = 180
    style = (
        f"FontSize={output.preset.subtitle_font_size},"
        f"Outline=2,Shadow=1,Alignment={alignment},MarginV={margin_v}"
    )
    return f"subtitles=filename='{_escape_filter_value(srt_path)}':force_style='{style}'"


def _escape_filter_value(path: Path) -> str:
    # Escape characters that have special meaning inside an ffmpeg filtergraph value.
    # Backslash must come first so subsequent inserted backslashes are not re-escaped.
    text = str(path)
    text = text.replace("\\", "\\\\")
    for ch in (":", ",", "'", "[", "]", ";"):
        text = text.replace(ch, "\\" + ch)
    return text


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
