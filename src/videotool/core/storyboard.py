from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from videotool.core.scene_timing import DEFAULT_MIN_HOLD_SECONDS, solve_durations


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
# Chapter separator the prompt author writes ahead of a chapter's first scene, e.g.
# "=== CHƯƠNG 541 ===". Only the keyword and the number are required — the surrounding
# decoration varies between authors and episodes.
PROMPT_CHAPTER_RE = re.compile(r"^[\s\-=#*]*chương[\s_]+(\d+)", re.IGNORECASE)
# Scene header inside the same file, e.g. "--- SCENE 001 ---".
PROMPT_SCENE_RE = re.compile(r"^[\s\-=#*]*scene[\s_]+(\d+)", re.IGNORECASE)
# Scene number carried by a generated asset's filename, e.g. "____SCENE_214_____212.jpeg".
ASSET_SCENE_RE = re.compile(r"scene[\s_-]*(\d+)", re.IGNORECASE)
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


def discover_scene_videos(video_dir: Path) -> list[Path]:
    """Return video clips in ``video_dir`` (by extension), natural-sorted by name.

    Missing dir → empty list (a chapter may legitimately have no b-roll clips).
    """
    if not video_dir.is_dir():
        return []
    videos = [
        path
        for path in video_dir.iterdir()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(videos, key=lambda path: natural_sort_key(path.name))


def interleave_media_by_story_order(
    images: list[Path],
    videos: list[Path],
) -> list[tuple[str, Path]]:
    """Merge images and video clips into one story-ordered list, spreading the clips evenly.

    Both folders number their assets sequentially along the same narration (``scene_001`` …),
    but image and video counts differ — and either may be short of the prompt count when some
    generations failed. So absolute file numbers are NOT comparable. Instead each asset is
    placed at its normalized story position ``(index + 0.5) / count`` within its own list and
    the two lists are merged by that position. This drapes the available clips across the whole
    timeline (never bunched at the front) regardless of how many of each survived.

    Returns ``(kind, path)`` tuples where ``kind`` is ``"image"`` or ``"video"``.
    """
    placed: list[tuple[float, str, Path]] = []
    for index, image in enumerate(images):
        placed.append(((index + 0.5) / len(images), "image", image))
    for index, video in enumerate(videos):
        # Bias clips a hair earlier so a clip and an image at the same slot keep the clip first.
        placed.append(((index + 0.5) / len(videos) - 1e-6, "video", video))
    placed.sort(key=lambda item: item[0])
    return [(kind, path) for _position, kind, path in placed]


def parse_prompt_chapters(prompts_path: Path) -> dict[int, int]:
    """Map prompt scene number -> chapter number, read from the file's chapter separators.

    The prompt file lists one block per scene ("--- SCENE 001 ---") and the author writes a
    separator ("=== CHƯƠNG 541 ===") ahead of each chapter's first scene. Scenes before the
    first separator stay unmapped, and a file carrying no separator at all yields ``{}`` —
    both leave the caller on the plain even split.
    """
    mapping: dict[int, int] = {}
    chapter: int | None = None
    for line in prompts_path.read_text(encoding="utf-8").splitlines():
        chapter_match = PROMPT_CHAPTER_RE.match(line)
        if chapter_match:
            chapter = int(chapter_match.group(1))
            continue
        scene_match = PROMPT_SCENE_RE.match(line)
        if scene_match and chapter is not None:
            mapping[int(scene_match.group(1))] = chapter
    return mapping


def asset_scene_numbers(paths: list[Path]) -> list[int] | None:
    """Scene number per asset, parsed from "SCENE_<n>" in the filename.

    Generated assets keep the prompt's scene number in their name, so a scene whose image
    failed to generate leaves a gap instead of shifting every later file down one.

    Returns ``None`` when any name lacks a number or two names share one. Callers must NOT
    quietly fall back to list position: joining a scene plan to the images by position is the
    one mistake that mistimes a whole episode without any visible symptom, so an unusable set
    of filenames has to be reported, not guessed around.
    """
    numbers: list[int] = []
    for path in paths:
        match = ASSET_SCENE_RE.search(path.stem)
        if match is None:
            return None
        numbers.append(int(match.group(1)))
    return numbers if len(set(numbers)) == len(numbers) else None


def _desired_starts_from_anchors(
    ordered: list[tuple[str, Path]],
    images: list[Path],
    plan_rows: list,
    cues: list,
) -> tuple[list[float | None], object] | None:
    """Per-position start times taken from each scene's narration anchor.

    Images are matched to plan rows BY SCENE NUMBER read out of the filename, never by
    position, so a scene whose image failed to generate leaves a gap instead of shifting every
    later image onto the wrong words.
    """
    from videotool.core.anchor_match import locate_anchors
    from videotool.core.logging import console

    numbers = asset_scene_numbers(images)
    if numbers is None:
        console.print(
            "[yellow]WARNING[/yellow] image filenames carry no usable scene number, so the "
            "scene plan cannot be matched to them; timing falls back to an even split"
        )
        return None

    times, report = locate_anchors([row.anchor for row in plan_rows], cues)
    by_scene = {row.scene: time for row, time in zip(plan_rows, times)}
    if not any(by_scene.get(number) is not None for number in numbers):
        return None

    time_of_image = {image: by_scene.get(number) for image, number in zip(images, numbers)}
    desired: list[float | None] = []
    for kind, path in ordered:
        desired.append(time_of_image.get(path) if kind == "image" else None)
    return desired, report


def _desired_starts_from_chapters(
    ordered: list[tuple[str, Path]],
    images: list[Path],
    image_chapters: dict[Path, int | None],
    chapter_starts: dict[int, float],
) -> list[float | None] | None:
    """Per-position start times that pin only each chapter's FIRST image.

    The images inside a chapter get no time of their own — the solver spaces them evenly
    between the chapter boundaries it is given. That is the whole chapter tier: the error is
    reset to zero at every chapter marker, which is where a viewer clicks and looks.
    """
    desired: list[float | None] = []
    seen: set[int] = set()
    pinned = 0
    for kind, path in ordered:
        chapter = image_chapters.get(path) if kind == "image" else None
        if kind != "image" or chapter is None or chapter in seen or chapter not in chapter_starts:
            desired.append(None)
            continue
        seen.add(chapter)
        desired.append(chapter_starts[chapter])
        pinned += 1
    return desired if pinned else None


def resolve_scene_durations(
    ordered: list[tuple[str, Path]],
    video_durations: dict[Path, float],
    images: list[Path],
    window: tuple[float, float],
    *,
    plan_rows: list | None = None,
    cues: list | None = None,
    prompt_chapters: dict[int, int] | None = None,
    chapter_starts: dict[int, float] | None = None,
    floor: float = DEFAULT_MIN_HOLD_SECONDS,
) -> tuple[list[float], dict]:
    """Durations per position plus a record of how they were decided.

    Three tiers, tried best first, and they differ ONLY in which start times they ask for —
    every one of them ends in the same solver, so the minimum hold and the "totals exactly the
    narration" rule cannot drift apart between them:

    - ``anchor``  every image is placed at the words it illustrates;
    - ``chapter`` each chapter's first image is placed, the rest spaced inside the chapter;
    - ``even``    nothing is known, so images share the episode equally (the old behaviour).

    Falling through to a lower tier is normal and never fatal: the scene plan is written by a
    tool outside this repo and an episode may simply not have one.
    """
    from videotool.core.logging import console

    clip_durations = [
        video_durations[path] if kind == "video" else 0.0 for kind, path in ordered
    ]
    image_count = sum(1 for kind, _path in ordered if kind == "image")

    if plan_rows and cues:
        resolved = _desired_starts_from_anchors(ordered, images, plan_rows, cues)
        if resolved is not None:
            desired, report = resolved
            console.print(
                f"Timing: anchored — {report.matched}/{report.total} scene(s) located in the "
                f"narration ({report.exact} exact, {report.prefix} shortened, "
                f"{report.missing} spaced between neighbours)"
            )
            return solve_durations(
                [kind for kind, _ in ordered], clip_durations, desired, window, floor
            ), {
                "source": "anchor",
                "anchors_matched": report.matched,
                "anchors_total": report.total,
                "min_hold_seconds": floor,
            }

    chapter_of_image = _chapter_map(images, plan_rows, prompt_chapters)
    if chapter_of_image and chapter_starts:
        desired = _desired_starts_from_chapters(
            ordered, images, chapter_of_image, chapter_starts
        )
        if desired is not None:
            console.print(
                f"Timing: per chapter — {len({c for c in chapter_of_image.values() if c})} "
                f"chapter(s) pinned to the narration SRT"
            )
            return solve_durations(
                [kind for kind, _ in ordered], clip_durations, desired, window, floor
            ), {"source": "chapter", "min_hold_seconds": floor}

    console.print(
        "[yellow]WARNING[/yellow] Timing: EVEN SPLIT — no scene plan matched, so the images "
        "are NOT aligned to the narration"
    )
    return solve_durations(
        [kind for kind, _ in ordered], clip_durations, [None] * len(ordered), window, floor
    ), {"source": "even", "min_hold_seconds": floor}


def _chapter_map(
    images: list[Path],
    plan_rows: list | None,
    prompt_chapters: dict[int, int] | None,
) -> dict[Path, int | None]:
    """Which chapter each image belongs to, from the scene plan or the prompt separators."""
    numbers = asset_scene_numbers(images)
    if numbers is None:
        return {}
    by_scene: dict[int, int | None] = {}
    if plan_rows:
        by_scene = {row.scene: row.chapter for row in plan_rows}
    elif prompt_chapters:
        by_scene = dict(prompt_chapters)
    if not by_scene:
        return {}
    return {image: by_scene.get(number) for image, number in zip(images, numbers)}


def build_even_split_storyboard(
    image_dir: Path,
    voice_duration: float,
    *,
    video_dir: Path | None = None,
    motions: tuple[str, ...] = MOTION_CYCLE,
    transition: str = "crossfade",
    intro_image: Path | None = None,
    ending_image: Path | None = None,
    plan_rows: list | None = None,
    cues: list | None = None,
    prompt_chapters: dict[int, int] | None = None,
    chapter_starts: dict[int, float] | None = None,
    floor: float = DEFAULT_MIN_HOLD_SECONDS,
) -> tuple[list[dict], dict]:
    """Build a storyboard spanning ``voice_duration`` across the folder's images and clips.

    Images and video clips (from ``video_dir``) are interleaved by story order so the clips
    are spread across the whole timeline, not bunched together. Video clips keep their real
    on-disk duration; the remaining time is split evenly across the still images. Motion
    rotates through ``motions`` (images only — clips carry their own motion). Paths are emitted
    as-is (the caller relativizes to the job dir).

    Both ``intro_image`` and ``ending_image`` overlay the narration (no added time): the intro
    holds the first ``INTRO_SECONDS`` and the ending the last ``OUTRO_SECONDS``, with the image
    split base shrinking by each so the storyboard always equals ``voice_duration``. This keeps
    the ending card flush with the voice end — so when an outro CTA is later spliced on, its
    title card lines up with the CTA voice instead of lagging behind a tail that runs past it.
    Each is skipped (with a warning) when the voice is too short to host it.

    Image timing comes from resolve_scene_durations, which picks the best tier the inputs
    allow: ``plan_rows`` + ``cues`` place every image at the words it illustrates; failing
    that, a chapter map plus ``chapter_starts`` pins each chapter; failing that, the images
    share the episode equally. Returns the scenes and the name of the tier used, so the caller
    can record which one an episode actually got, as a mapping ready for job.yaml's `timing`.
    """
    images = discover_scene_images(image_dir)
    videos = discover_scene_videos(video_dir) if video_dir is not None else []
    # Exclude intro/ending from the middle media in case they live inside the same folder.
    framing = {path.resolve() for path in (intro_image, ending_image) if path is not None}
    if framing:
        images = [image for image in images if image.resolve() not in framing]
        videos = [video for video in videos if video.resolve() not in framing]
    if not images and not videos:
        raise ValueError(f"No images or videos found in {image_dir}")

    from videotool.core.logging import console

    use_intro = intro_image is not None and voice_duration > INTRO_SECONDS
    if intro_image is not None and not use_intro:
        console.print(
            f"[yellow]WARNING[/yellow] voice ({voice_duration:.1f}s) too short for a "
            f"{INTRO_SECONDS:.0f}s intro; skipping intro image"
        )
    # The ending overlay must fit alongside the intro overlay, so test it against the remainder.
    remaining_for_ending = voice_duration - (INTRO_SECONDS if use_intro else 0.0)
    use_ending = ending_image is not None and remaining_for_ending > OUTRO_SECONDS
    if ending_image is not None and not use_ending:
        console.print(
            f"[yellow]WARNING[/yellow] voice ({voice_duration:.1f}s) too short for a "
            f"{OUTRO_SECONDS:.0f}s ending overlay; skipping ending image"
        )

    ordered = interleave_media_by_story_order(images, videos)
    video_durations = {path: _probe_duration(path) for kind, path in ordered if kind == "video"}

    durations, timing = resolve_scene_durations(
        ordered,
        video_durations,
        images,
        (INTRO_SECONDS if use_intro else 0.0, voice_duration - (OUTRO_SECONDS if use_ending else 0.0)),
        plan_rows=plan_rows,
        cues=cues,
        prompt_chapters=prompt_chapters,
        chapter_starts=chapter_starts,
        floor=floor,
    )

    scenes: list[dict] = []
    if use_intro:
        scenes.append(_static_scene(intro_image, INTRO_SECONDS))
    image_index = 0
    for position, (kind, path) in enumerate(ordered):
        if kind == "video":
            scenes.append(
                {
                    "video": str(path),
                    "duration": durations[position],
                    "motion": "static",
                    "transition": transition,
                }
            )
        else:
            scenes.append(
                {
                    "image": str(path),
                    "duration": durations[position],
                    "motion": motions[image_index % len(motions)],
                    "transition": transition,
                }
            )
            image_index += 1
    if use_ending:
        scenes.append(_static_scene(ending_image, OUTRO_SECONDS))

    for number, scene in enumerate(scenes, start=1):
        scene["scene"] = number
    # Reorder keys so "scene" leads each mapping in the emitted YAML.
    return [{"scene": scene.pop("scene"), **scene} for scene in scenes], timing


def _probe_duration(path: Path) -> float:
    """Real duration of a video clip; raises if FFprobe cannot read it (better than a
    silently-wrong storyboard length)."""
    from videotool.core.media_probe import probe_media

    duration = probe_media(path).duration or 0.0
    if duration <= 0:
        raise ValueError(f"Video clip has no usable duration: {path}")
    return round(duration, 3)


def _static_scene(image: Path, duration: float) -> dict:
    return {
        "image": str(image),
        "duration": duration,
        "motion": "static",
        "transition": "crossfade",
    }
