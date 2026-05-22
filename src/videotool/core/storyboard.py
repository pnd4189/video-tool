from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm")
MOTION_CHOICES = {
    "zoom-in",
    "zoom-out",
    "slow-push",
    "pan-left",
    "pan-right",
    "pan-up",
    "pan-down",
    "ken-burns",
}
TRANSITION_CHOICES = {"cut", "fade", "crossfade", "dip-to-black"}
SCENE_RE = re.compile(r"^\[Scene\s+(\d+)\s*(?:[—-]\s*([^\]]+))?\]\s*$", re.IGNORECASE)
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


@dataclass(frozen=True)
class PromptScene:
    scene: int
    title: str
    image_prompt: str = ""
    video_prompt: str = ""
    duration: float = 8.0
    motion: str = "slow-push"
    transition: str = "crossfade"
    image: Path | None = None


def parse_prompt_file(path: Path) -> dict[int, tuple[str, str]]:
    scenes: dict[int, tuple[str, str]] = {}
    current_scene: int | None = None
    current_title = ""
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = SCENE_RE.match(line.strip())
        if match:
            if current_scene is not None:
                scenes[current_scene] = (current_title, "\n".join(lines).strip())
            current_scene = int(match.group(1))
            current_title = (match.group(2) or "").strip()
            lines = []
        elif current_scene is not None:
            lines.append(line)
    if current_scene is not None:
        scenes[current_scene] = (current_title, "\n".join(lines).strip())
    return scenes


def build_storyboard(
    image_prompts: Path,
    video_prompts: Path,
    media_dir: Path,
    default_duration: float = 8.0,
) -> list[PromptScene]:
    image_scenes = parse_prompt_file(image_prompts)
    video_scenes = parse_prompt_file(video_prompts)
    scene_numbers = sorted(set(image_scenes) | set(video_scenes))
    return [
        _build_scene(scene_number, image_scenes, video_scenes, media_dir, default_duration)
        for scene_number in scene_numbers
    ]


def select_effects(video_prompt: str) -> tuple[str, str]:
    text = video_prompt.lower()
    if "quick zoom" in text or "zoom in" in text:
        motion = "zoom-in"
    elif "zoom out" in text or "panning out" in text:
        motion = "zoom-out"
    elif "pan right" in text or "panning right" in text:
        motion = "pan-right"
    elif "pan left" in text or "panning left" in text:
        motion = "pan-left"
    elif "tracking" in text or "push in" in text or "slow push" in text:
        motion = "slow-push"
    else:
        motion = "ken-burns"

    if "explosive" in text or "fast-paced" in text:
        transition = "crossfade"
    elif "quiet" in text or "serene" in text or "peaceful" in text:
        transition = "fade"
    else:
        transition = "crossfade"
    return motion, transition


def find_scene_media(media_dir: Path, scene_number: int) -> Path:
    stem = f"scene-{scene_number:03}"
    for extension in IMAGE_EXTENSIONS + VIDEO_EXTENSIONS:
        candidate = media_dir / f"{stem}{extension}"
        if candidate.exists():
            return candidate
    return media_dir / f"{stem}.png"


def _build_scene(
    scene_number: int,
    image_scenes: dict[int, tuple[str, str]],
    video_scenes: dict[int, tuple[str, str]],
    media_dir: Path,
    default_duration: float,
) -> PromptScene:
    image_title, image_prompt = image_scenes.get(scene_number, ("", ""))
    video_title, video_prompt = video_scenes.get(scene_number, ("", ""))
    duration = _duration_from_title(video_title) or default_duration
    motion, transition = select_effects(video_prompt)
    return PromptScene(
        scene=scene_number,
        title=image_title or video_title,
        image_prompt=image_prompt,
        video_prompt=video_prompt,
        duration=duration,
        motion=motion,
        transition=transition,
        image=find_scene_media(media_dir, scene_number),
    )


def _duration_from_title(title: str) -> float | None:
    match = DURATION_RE.search(title)
    return float(match.group(1)) if match else None
