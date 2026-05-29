from __future__ import annotations

from pathlib import Path

from videotool.core.timeline import Timeline, TimelineOutput, TimelineScene
from videotool.render.profiles import RenderProfile


def is_image(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


def codec_args(profile: RenderProfile) -> list[str]:
    args = ["-c:v", profile.encoder]
    if profile.preset:
        args.extend(["-preset", profile.preset])
    if profile.crf is not None:
        args.extend(["-crf", str(profile.crf)])
    args.extend(["-pix_fmt", "yuv420p"])
    return args


def metadata_args(timeline: Timeline) -> list[str]:
    args: list[str] = []
    if timeline.title:
        args.extend(["-metadata", f"title={timeline.title}"])
    if timeline.description:
        args.extend(["-metadata", f"description={timeline.description}"])
        args.extend(["-metadata", f"comment={timeline.description}"])
    if timeline.author:
        args.extend(["-metadata", f"artist={timeline.author}"])
    return args


def scene_filter(index: int, scene: TimelineScene, output: TimelineOutput, label: str) -> str:
    width = output.preset.width
    height = output.preset.height
    fps = output.preset.fps
    if is_image(scene.media_path):
        if scene.motion == "static":
            # Designed frames (thumbnail/credits): fit + letterbox so nothing is cropped,
            # and hold still (no zoompan). Used for intro/ending images.
            return (
                f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},"
                f"trim=duration={scene.duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[{label}]"
            )
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


# Scenes in audio-story videos can run tens of seconds, so motion spread linearly over
# a long scene must stay large enough to be visible per-second (and to keep YouTube from
# treating the frame as static). These are deliberately stronger than a subtle Ken Burns.
ZOOM_AMPLITUDE = 0.30
ZOOM_MAX = 1.0 + ZOOM_AMPLITUDE
PAN_ZOOM = 1.22


def _motion_expr(motion: str, frames: int) -> tuple[str, str, str]:
    center_x = "iw/2-(iw/zoom/2)"
    center_y = "ih/2-(ih/zoom/2)"
    pan = f"{PAN_ZOOM:g}"
    if motion == "zoom-out":
        return f"max(1.0,{ZOOM_MAX:g}-{ZOOM_AMPLITUDE:g}*on/{frames})", center_x, center_y
    if motion == "pan-left":
        return pan, f"(iw-iw/zoom)*(1-on/{frames})", center_y
    if motion == "pan-right":
        return pan, f"(iw-iw/zoom)*on/{frames}", center_y
    if motion == "pan-up":
        return pan, center_x, f"(ih-ih/zoom)*(1-on/{frames})"
    if motion == "pan-down":
        return pan, center_x, f"(ih-ih/zoom)*on/{frames}"
    return f"min({ZOOM_MAX:g},1.0+{ZOOM_AMPLITUDE:g}*on/{frames})", center_x, center_y
