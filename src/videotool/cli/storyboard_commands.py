from __future__ import annotations

from pathlib import Path

import yaml

from videotool.core.job_spec import JobSpec
from videotool.core.logging import console
from videotool.core.media_probe import probe_media
from videotool.core.parallax_link import link_parallax_clips
from videotool.core.storyboard import build_even_split_storyboard, build_storyboard


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
) -> None:
    """Generate an even-split storyboard from an images folder (+ optional video-clip folder)
    and the voice duration, writing it into an existing job.yaml and preserving other keys.

    Video clips are interleaved with images by story order so b-roll is spread across the whole
    timeline. An existing storyboard block is overwritten with a warning naming its old scene
    count.
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
    scenes = build_even_split_storyboard(
        images_dir,
        voice_duration,
        video_dir=videos_dir,
        intro_image=intro_image,
        ending_image=ending_image,
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
