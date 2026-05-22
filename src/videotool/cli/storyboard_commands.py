from __future__ import annotations

from pathlib import Path

import yaml

from videotool.core.job_spec import JobSpec
from videotool.core.logging import console
from videotool.core.storyboard import build_storyboard


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
        "outputs": [{"preset": "youtube-16x9"}, {"preset": "shorts-9x16"}],
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


def _relative_or_original(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path
