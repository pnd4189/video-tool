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
    "static",
}
# Intro thumbnail overlays the first seconds of the voice (no added time); the ending image
# is appended as an extra outro after the voice ends. Voice is later padded with silence.
INTRO_SECONDS = 10.0
OUTRO_SECONDS = 10.0
TRANSITION_CHOICES = {"cut", "fade", "crossfade", "dip-to-black"}
SCENE_RE = re.compile(r"^\[Scene\s+(\d+)\s*(?:[—-]\s*([^\]]+))?\]\s*$", re.IGNORECASE)
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)
DIGIT_RUN_RE = re.compile(r"(\d+)")
# Cycled across scenes so an even-split board still varies its motion.
MOTION_CYCLE = ("slow-push", "zoom-in", "pan-right", "zoom-out", "pan-left")


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


def natural_sort_key(name: str) -> list[tuple[int, object]]:
    """Split a filename into text/number runs so ``scene_2`` sorts before ``scene_10``.

    Naming-agnostic: works for any names. Each run is type-tagged ``(0, int)`` or
    ``(1, str)`` so numeric and text runs never compare directly (numbers sort first).
    """
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in DIGIT_RUN_RE.split(name)
        if part != ""
    ]


def discover_scene_images(image_dir: Path) -> list[Path]:
    """Return image files in ``image_dir`` (by extension), natural-sorted by name."""
    images = [
        path
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return sorted(images, key=lambda path: natural_sort_key(path.name))


def build_even_split_storyboard(
    image_dir: Path,
    voice_duration: float,
    *,
    motions: tuple[str, ...] = MOTION_CYCLE,
    transition: str = "crossfade",
    intro_image: Path | None = None,
    ending_image: Path | None = None,
) -> list[dict]:
    """Build a storyboard that splits ``voice_duration`` evenly across the folder's images.

    The middle images share ``round(base/N, 3)`` and the last middle image absorbs the
    rounding remainder. Motion rotates through ``motions``. Image paths are emitted as-is
    (the caller relativizes to the job dir).

    ``intro_image`` is prepended as a static ``INTRO_SECONDS`` scene overlaying the start of
    the voice — the middle split base shrinks by ``INTRO_SECONDS`` so total time is unchanged.
    It is skipped (with a warning) when the voice is too short to host it. ``ending_image`` is
    appended as a static ``OUTRO_SECONDS`` scene that extends the video past the voice.
    """
    images = discover_scene_images(image_dir)
    # Exclude intro/ending from the middle images in case they live inside the same folder.
    framing = {path.resolve() for path in (intro_image, ending_image) if path is not None}
    if framing:
        images = [image for image in images if image.resolve() not in framing]
    if not images:
        raise ValueError(f"No images found in {image_dir}")

    use_intro = intro_image is not None and voice_duration > INTRO_SECONDS
    if intro_image is not None and not use_intro:
        from videotool.core.logging import console

        console.print(
            f"[yellow]WARNING[/yellow] voice ({voice_duration:.1f}s) too short for a "
            f"{INTRO_SECONDS:.0f}s intro; skipping intro image"
        )

    base = voice_duration - (INTRO_SECONDS if use_intro else 0.0)
    count = len(images)
    each = round(base / count, 3)
    durations = [each] * (count - 1)
    durations.append(round(base - each * (count - 1), 3))

    scenes: list[dict] = []
    if use_intro:
        scenes.append(_static_scene(intro_image, INTRO_SECONDS))
    for index, image in enumerate(images):
        scenes.append(
            {
                "image": str(image),
                "duration": durations[index],
                "motion": motions[index % len(motions)],
                "transition": transition,
            }
        )
    if ending_image is not None:
        scenes.append(_static_scene(ending_image, OUTRO_SECONDS))

    for number, scene in enumerate(scenes, start=1):
        scene["scene"] = number
    # Reorder keys so "scene" leads each mapping in the emitted YAML.
    return [
        {"scene": scene.pop("scene"), **scene}
        for scene in scenes
    ]


def _static_scene(image: Path, duration: float) -> dict:
    return {
        "image": str(image),
        "duration": duration,
        "motion": "static",
        "transition": "crossfade",
    }
