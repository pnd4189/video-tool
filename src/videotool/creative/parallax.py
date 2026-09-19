"""Parallax bookkeeping shared by the cloud runner, local prepare and lint.

Episodes ship pre-rendered DepthFlow clips in `Parallax/`; `parallax-link` swaps them in for free.
`enhance.parallax` otherwise makes the render estimate depth for every remaining still — hours of
work — so these helpers count what is left and keep the intro/ending title cards out of it.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def title_cards(job_dir: Path, data: dict) -> set[Path]:
    """The intro/ending images: static title-card scenes no Parallax/ clip exists for."""
    inputs = data.get("inputs") or {}
    return {(Path(job_dir) / str(inputs[k])).resolve() for k in ("intro_image", "ending_image") if inputs.get(k)}


def story_stills(job_dir: Path, data: dict) -> int:
    """Still scenes other than the title cards — the ones depth parallax would work on."""
    cards = title_cards(job_dir, data)
    return sum(
        1 for scene in (data.get("storyboard") or [])
        if scene.get("image") and (Path(job_dir) / str(scene["image"])).resolve() not in cards
    )


def keep_title_cards_static(job_dir: Path, job_yaml: Path) -> bool:
    """Switch enhance.parallax off once every story still is already a Parallax/ clip; True when it
    did. The only stills left are then the title cards, and depth parallax would just warp them,
    lettering included. When story stills remain (an explicit opt-in), the flag stays on."""
    data = yaml.safe_load(Path(job_yaml).read_text(encoding="utf-8")) or {}
    enhance = data.get("enhance") or {}
    if not enhance.get("parallax") or story_stills(job_dir, data):
        return False
    enhance["parallax"] = False
    data["enhance"] = enhance
    Path(job_yaml).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return True
