"""The description `package` will write, rendered on lint's stand-in before the render slot.

Same template, intro-CTA-shifted chapters and recap/summary as the box's package step, so lint can
check its length and placeholders and the user can read it before anything is staged.
"""

from __future__ import annotations

import json
from pathlib import Path


def description_preview(job_dir: Path, data: dict, cta_s: float) -> str | None:
    from videotool.package.youtube import format_chapters_block, render_description_template
    from videotool.render.cta_compose import offset_chapters

    named = (data.get("inputs") or {}).get("description_template")  # the box's choice, first
    template = job_dir / named if named and (job_dir / named).is_file() else \
        next(iter(sorted(job_dir.glob("*_DESCRIPTION_TEMPLATE.txt"))), None)
    if template is None:
        return None
    chapters_path = job_dir / "outputs" / "chapters.json"
    chapters = [(c["start"], c["title"]) for c in json.loads(chapters_path.read_text(encoding="utf-8"))] \
        if chapters_path.exists() else []
    project = data.get("project") or {}
    return render_description_template(
        template.read_text(encoding="utf-8"),
        chapters_block=format_chapters_block(offset_chapters(chapters, cta_s) if cta_s else chapters),
        recap_prev=project.get("recap_previous", ""), summary=project.get("description", ""),
    )
