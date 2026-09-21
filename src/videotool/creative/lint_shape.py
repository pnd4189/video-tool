"""`creative lint` checks on the shape of creative.yaml itself: keys the pipeline reads, input paths.

A key the pipeline never reads is ignored without a word, and an input path is resolved inside the
episode folder on the render box — both passed a local lint and still broke an episode (ĐẠO SĨ
Chap 22: `enhance.atmosphere` dropped the overlay, an absolute `inputs.description_template`
killed the Kaggle run six minutes in).
"""

from __future__ import annotations

import difflib
from pathlib import Path, PurePosixPath

Found = tuple[list[str], list[str]]

# Every creative key something downstream reads (apply_creative, the cloud runner, prepare).
KNOWN_KEYS = {
    "": {"project", "audio", "enhance", "captions", "render", "inputs"},
    "project": {"title", "description", "recap_previous", "metadata", "chapters"},
    "audio": {"music_schedule"},
    "enhance": {"mood", "grain", "vignette", "glow", "flicker", "color_grade", "parallax",
                "parallax_on_box", "overlay", "sfx"},
    "enhance.sfx": {"pack", "cues"},
    "captions": {"renumber"},
    "render": {"bitrate_cap"},
}
# Mistakes seen in agent-authored creatives, where a spelling match would not find the key meant.
LIKELY_MEANT = {"atmosphere": "overlay", "fireflies": "overlay", "particles": "overlay",
                "particle_overlay": "overlay", "music": "music_schedule"}


def _known() -> dict[str, set[str]]:
    from videotool.core.job_spec import InputSpec, MetadataSpec

    return {**KNOWN_KEYS, "inputs": set(InputSpec.model_fields),
            "project.metadata": set(MetadataSpec.model_fields)}


def check_keys(creative: dict) -> Found:
    known = _known()
    errors: list[str] = []

    def walk(node: object, path: str) -> None:
        if not isinstance(node, dict) or path not in known:
            return
        for key, value in node.items():
            where = f"{path}.{key}" if path else str(key)
            if key in known[path]:
                walk(value, where)
                continue
            meant = LIKELY_MEANT.get(str(key))
            hint = meant if meant in known[path] else \
                next(iter(difflib.get_close_matches(str(key), known[path], n=1)), None)
            errors.append(f"unknown creative key `{where}` — nothing reads it, so it has no effect"
                          + (f"; did you mean `{path + '.' if path else ''}{hint}`?" if hint else ""))

    walk(creative, "")
    return errors, []


def check_inputs(creative: dict, files: list[str]) -> Found:
    """Each `inputs.*` override must name something inside the episode folder, relative to it."""
    errors: list[str] = []
    for key, value in ((creative.get("inputs") or {}).items()):
        path = PurePosixPath(str(value).replace("\\", "/"))
        if Path(str(value)).is_absolute() or ".." in path.parts:
            errors.append(f"inputs.{key} = {value!r}: use a path inside the episode folder (the render box "
                          "resolves it there), e.g. the bare file name")
            continue
        rel = path.as_posix().rstrip("/")
        if rel not in files and not any(f.startswith(rel + "/") for f in files):
            errors.append(f"inputs.{key} = {value!r} is not in the episode folder")
    return errors, []
