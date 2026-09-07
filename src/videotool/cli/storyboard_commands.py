from __future__ import annotations

from pathlib import Path

import yaml

from videotool.core.anchor_match import parse_srt_cues
from videotool.core.chapter_timing import chapter_starts_from_srt
from videotool.core.job_spec import JobSpec
from videotool.core.logging import console
from videotool.core.media_probe import probe_media
from videotool.core.parallax_link import link_parallax_clips
from videotool.core.scene_plan import find_scene_plan, parse_scene_plan
from videotool.core.scene_timing import DEFAULT_MIN_HOLD_SECONDS
from videotool.core.storyboard import (
    build_even_split_storyboard,
    build_storyboard,
    parse_prompt_chapters,
)


def plan_storyboard(
    image_prompts: Path,
    video_prompts: Path,
    media_dir: Path,
    voice: str,
    output: Path,
    music: str | None,
    title: str | None,
) -> None:
    scenes = build_storyboard(image_prompts, video_prompts, media_dir)
    media_value = _relative_or_original(media_dir, output.parent)
    payload = {
        "version": 1,
        "project": {"title": title or output.parent.name or "storyboard-video", "language": "vi"},
        "inputs": {"voice": voice, "media_dir": str(media_value)},
        "outputs": [{"preset": "youtube-16x9"}],
        "storyboard": [
            {
                "scene": scene.scene,
                "image": str(_relative_or_original(scene.image or media_dir / f"scene-{scene.scene:03}.png", output.parent)),
                "duration": scene.duration,
                "motion": scene.motion,
                "transition": scene.transition,
            }
            for scene in scenes
        ],
        "captions": {"mode": "srt-only"},
        "assets": {"policy": "allow-missing-local"},
        "render": {"encoder": "libx264-balanced", "temp_dir": ".videotool/tmp"},
    }
    if music:
        payload["inputs"]["music"] = music
    JobSpec.model_validate(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
    console.print(f"Wrote storyboard job with {len(scenes)} scene(s): {output}")


def auto_storyboard(
    job_path: Path,
    images_dir: Path,
    voice_duration: float | None = None,
    videos_dir: Path | None = None,
    prompts_file: Path | None = None,
    scene_plan_file: Path | None = None,
    floor: float = DEFAULT_MIN_HOLD_SECONDS,
) -> None:
    """Generate a storyboard from an images folder (+ optional video-clip folder) and the
    voice duration, writing it into an existing job.yaml and preserving other keys.

    Video clips are interleaved with images by story order so b-roll is spread across the whole
    timeline. Image timing uses the best source the folder offers — the scene plan's narration
    anchors, else its chapter column, else an equal share each — and the SRT is located here
    rather than demanded from the caller. An existing storyboard block is overwritten with a
    warning naming its old scene count.
    """
    job_dir = job_path.parent
    data = yaml.safe_load(job_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Job file must contain a YAML mapping: {job_path}")
    if voice_duration is None:
        voice_duration = probe_media(job_dir / data["inputs"]["voice"]).duration
    if not voice_duration or voice_duration <= 0:
        raise ValueError(f"Voice track has no usable duration: {data['inputs']['voice']}")

    inputs = data.get("inputs", {})
    intro_image = _job_input_path(inputs.get("intro_image"), job_dir)
    ending_image = _job_input_path(inputs.get("ending_image"), job_dir)
    srt_text = _read_narration_srt(job_dir)
    plan_rows = _load_scene_plan(job_dir, scene_plan_file)
    scenes, timing = build_even_split_storyboard(
        images_dir,
        voice_duration,
        video_dir=videos_dir,
        intro_image=intro_image,
        ending_image=ending_image,
        plan_rows=plan_rows,
        cues=parse_srt_cues(srt_text) if srt_text else None,
        prompt_chapters=_load_prompt_chapters(job_dir, prompts_file),
        chapter_starts=chapter_starts_from_srt(srt_text) if srt_text else None,
        floor=floor,
    )
    for scene in scenes:
        key = "video" if "video" in scene else "image"
        scene[key] = str(_relative_or_original(Path(scene[key]), job_dir))

    existing = data.get("storyboard")
    if existing:
        console.print(
            f"[yellow]WARNING[/yellow] overwriting existing storyboard ({len(existing)} scene(s))"
        )
    data["storyboard"] = scenes
    data["timing"] = timing
    JobSpec.model_validate(data)
    job_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    console.print(f"Wrote {len(scenes)} scene(s) to {job_path}")


def link_parallax(job_path: Path, clips_dir: Path) -> dict[str, int]:
    """Swap image scenes for matching parallax clips in ``clips_dir`` and rewrite job.yaml.

    ``clips_dir`` resolves relative to the job dir when not absolute. Returns swap counts.
    """
    job_dir = job_path.parent
    resolved = clips_dir if clips_dir.is_absolute() else (job_dir / clips_dir)
    if not resolved.is_dir():
        raise ValueError(f"Clips dir not found: {resolved}")
    data = yaml.safe_load(job_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "storyboard" not in data:
        raise ValueError(f"Job file has no storyboard to link: {job_path}")
    scenes, counts = link_parallax_clips(data["storyboard"], resolved, job_dir)
    data["storyboard"] = scenes
    JobSpec.model_validate(data)
    job_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    console.print(
        f"Linked parallax clips: swapped {counts['swapped']}, "
        f"missing {counts['missing']}, skipped-video {counts['skipped']}"
    )
    return counts


def _load_prompt_chapters(job_dir: Path, prompts_file: Path | None) -> dict[int, int] | None:
    """Scene -> chapter map from the image-prompt file, or None when there is nothing to read.

    This is the legacy third source, kept only so an older episode whose prompt file carries
    chapter separators still benefits. Its absence is the normal case now — the scene plan
    supplies both the anchors and the chapters — so a miss is silent; the tier that actually
    gets used is reported once by the resolver.
    """
    candidates = [prompts_file] if prompts_file else sorted(job_dir.glob("*image_prompts*.txt"))
    found = next((path for path in candidates if path and path.is_file()), None)
    return parse_prompt_chapters(found) or None if found else None


def _read_narration_srt(job_dir: Path) -> str | None:
    """The narration SRT for this job, found without the caller having to stage it first.

    Looks at the staged copy, then at the QA SRT the user supplies in the job folder. Resolving
    it here rather than demanding a particular step order is the point: the rule "copy the SRT
    before building the storyboard" lived in four documents and one runner, and four copies of
    a rule drift. Now there is no order left to get wrong.

    `captions.youtube.srt` is deliberately never read — it is shifted by the intro CTA, so
    timing scenes against it would drag every image late by the CTA's length.
    """
    staged = job_dir / "outputs" / "captions.srt"
    if staged.is_file():
        return staged.read_text(encoding="utf-8")
    for candidate in sorted(job_dir.glob("*_vi_qa.srt")) or sorted(job_dir.glob("*.srt")):
        if candidate.name != "captions.youtube.srt":
            return candidate.read_text(encoding="utf-8")
    console.print(
        "[yellow]WARNING[/yellow] no narration SRT found in the job folder; images cannot be "
        "timed to the words and will share the episode equally"
    )
    return None


def _load_scene_plan(job_dir: Path, explicit: Path | None) -> list | None:
    """Scene plan rows for this job, or None when the episode has no plan."""
    path = find_scene_plan(job_dir, explicit)
    if path is None:
        console.print(
            "[yellow]WARNING[/yellow] no scene plan found beside the prompts or in .work/; "
            "images cannot be timed to the words"
        )
        return None
    rows = parse_scene_plan(path)
    if not rows:
        console.print(f"[yellow]WARNING[/yellow] {path.name} has no usable rows")
        return None
    console.print(f"Scene plan: {path.name} ({len(rows)} scene(s))")
    return rows


def _job_input_path(value: object, job_dir: Path) -> Path | None:
    """Resolve an optional job-input image path (relative to the job dir) to absolute.

    The caller relativizes emitted scene paths afterward, so returning an absolute path
    keeps intro/ending images consistent with the discovered scene images.
    """
    if not value:
        return None
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (job_dir / candidate)


def _relative_or_original(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path
