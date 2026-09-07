"""Read the scene plan the prompt-writing step emits alongside the image prompts.

The plan is the only record of which part of the narration each image illustrates: one row
per scene, carrying the chapter the scene belongs to and a short verbatim excerpt of the
narration it depicts. videotool only ever reads it.

Rows are matched by COLUMN NAME from the header, never by position, so the same parser reads
both the full plan the prompt tool writes today and a trimmed sidecar carrying only the three
columns that matter here — and neither breaks when a column is added.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SCENE_COLUMN = "scene_id"
CHAPTER_COLUMN = "chapter"
ANCHOR_COLUMN = "source_anchor"

# Searched in order. The visible names come first because a file sitting beside the prompts
# travels with every copy anyone makes; `.work/` is hidden and survives transport by accident,
# which is exactly how episodes lost their timing data in the first place.
VISIBLE_PLAN_GLOBS = ("*scene_anchors*.md", "*scene-anchors*.md", "*scene_plan*.md")
HIDDEN_PLAN_RELATIVE = Path(".work") / "scene-plan.md"


@dataclass(frozen=True)
class ScenePlanRow:
    """One planned scene: its number, its chapter, and the narration it depicts."""

    scene: int
    chapter: int | None
    anchor: str


def find_scene_plan(job_dir: Path, explicit: Path | None = None) -> Path | None:
    """Locate the scene plan for a job folder, or None when the job has none.

    An explicit path always wins so a caller can point at a plan kept elsewhere.
    """
    if explicit is not None:
        return explicit if explicit.is_file() else None
    for glob in VISIBLE_PLAN_GLOBS:
        for candidate in sorted(job_dir.glob(glob)):
            if candidate.is_file():
                return candidate
    hidden = job_dir / HIDDEN_PLAN_RELATIVE
    return hidden if hidden.is_file() else None


def parse_scene_plan(path: Path) -> list[ScenePlanRow]:
    """Rows of the plan's markdown table, in file order.

    A row whose scene number or anchor is unusable is skipped rather than raising: the plan is
    written by a tool outside this repo, and one malformed row must not cost a whole render.
    """
    columns: dict[str, int] | None = None
    rows: list[ScenePlanRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = _split_table_row(line)
        if cells is None:
            continue
        if columns is None:
            columns = {name.strip().lower(): index for index, name in enumerate(cells)}
            if SCENE_COLUMN not in columns or ANCHOR_COLUMN not in columns:
                columns = None  # not the header yet; keep looking
            continue
        row = _build_row(cells, columns)
        if row is not None:
            rows.append(row)
    return rows


def _split_table_row(line: str) -> list[str] | None:
    """Cells of a markdown table row, or None when the line is not one.

    The `|---|---|` separator under the header is reported as not-a-row so callers never see it.
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    if set(stripped) <= set("|-: "):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _build_row(cells: list[str], columns: dict[str, int]) -> ScenePlanRow | None:
    scene_text = _cell(cells, columns, SCENE_COLUMN)
    anchor = _cell(cells, columns, ANCHOR_COLUMN)
    if not scene_text or not anchor:
        return None
    try:
        scene = int(scene_text)
    except ValueError:
        return None
    chapter_text = _cell(cells, columns, CHAPTER_COLUMN)
    try:
        chapter = int(chapter_text) if chapter_text else None
    except ValueError:
        chapter = None
    return ScenePlanRow(scene=scene, chapter=chapter, anchor=anchor)


def _cell(cells: list[str], columns: dict[str, int], name: str) -> str:
    index = columns.get(name)
    return cells[index] if index is not None and index < len(cells) else ""
