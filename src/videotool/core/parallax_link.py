"""Swap still-image scenes for pre-rendered 2.5D parallax clips at the data layer.

A separate GPU box (Colab + DepthFlow) renders one loopable motion clip per still and
drops them in a clips folder named ``<image-stem>.<videoext>``. This module rewrites the
job's storyboard so each matching image scene points at its clip instead — no render-code
change, because a video scene already loop+trims to its duration. Scenes without a matching
clip stay as stills (Ken Burns), so a partial clip set never breaks a render.
"""
from __future__ import annotations

from pathlib import Path

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".webm")


def find_clip(clips_dir: Path, stem: str) -> Path | None:
    """Return the clip in ``clips_dir`` whose stem matches ``stem`` (extension case-insensitive)."""
    if not clips_dir.is_dir():
        return None
    for entry in sorted(clips_dir.iterdir()):
        if entry.is_file() and entry.stem == stem and entry.suffix.lower() in VIDEO_EXTS:
            return entry
    return None


def _relative_or_original(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return path


def link_parallax_clips(
    scenes: list[dict], clips_dir: Path, job_dir: Path
) -> tuple[list[dict], dict[str, int]]:
    """Return scenes with each matched image scene swapped to its parallax clip, plus counts.

    Only scenes keyed ``image`` are considered; a scene already keyed ``video`` (b-roll, or an
    earlier swap) is left untouched, which makes re-runs a no-op.
    """
    counts = {"swapped": 0, "missing": 0, "skipped": 0}
    out: list[dict] = []
    for scene in scenes:
        if "image" not in scene or scene.get("video"):
            counts["skipped"] += 1
            out.append(scene)
            continue
        clip = find_clip(clips_dir, Path(str(scene["image"])).stem)
        if clip is None:
            counts["missing"] += 1
            out.append(scene)
            continue
        swapped = dict(scene)
        swapped.pop("image", None)
        swapped["video"] = str(_relative_or_original(clip, job_dir))
        swapped["motion"] = "static"  # the clip carries its own depth motion
        counts["swapped"] += 1
        out.append(swapped)
    return out, counts
