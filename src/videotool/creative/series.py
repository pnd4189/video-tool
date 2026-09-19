"""Series registry (`.agents/skills/make-video/references/series.yaml`) and title-list matching."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REGISTRY_RELATIVE = Path(".agents/skills/make-video/references/series.yaml")
METADATA_KEYS = ("channel", "channel_url", "original_author", "copyright")


def find_registry(start: Path | None = None) -> Path | None:
    """series.yaml found by walking up from `start` (default: cwd), then from this package's repo."""
    here = Path(__file__).resolve()
    for base in (Path(start or Path.cwd()).resolve(), here.parent):
        for folder in (base, *base.parents):
            candidate = folder / REGISTRY_RELATIVE
            if candidate.is_file():
                return candidate
    return None


def load_series(path: Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return list(data.get("series") or [])


def match_series(series: list[dict], names: list[str]) -> dict | None:
    """The series whose `stem_prefix` starts any of the given file names."""
    for entry in series:
        prefix = entry.get("stem_prefix")
        if prefix and any(name.startswith(prefix) for name in names):
            return entry
    return None


def _normalise(text: str, pipe_to_dash: bool) -> str:
    text = text.replace("`", " ")
    if pipe_to_dash:  # the list escapes the hook separator as `\|` inside a markdown table cell
        text = re.sub(r"\s*\\\|\s*", " - ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_status(title: str, entry: dict) -> tuple[str, str]:
    """('ok' | 'extended' | 'missing' | 'unverified', detail) for `title` against the series list.

    'extended' = the title is a listed title plus a trailing "(…)" — e.g. "(Tập Cuối)", which the
    user added for a final episode; worth a warning, not an error."""
    source = entry.get("title_source")
    if not source:
        return "unverified", "series has no title_source"
    try:
        listing = Path(source).read_text(encoding="utf-8")
    except OSError as exc:
        return "unverified", f"cannot read the title list ({exc.__class__.__name__}: {source})"
    pipe = bool(entry.get("title_pipe_to_dash"))
    haystack = _normalise(listing, pipe)
    wanted = _normalise(title, False)
    if wanted in haystack:
        return "ok", source
    base = re.sub(r"\s*\([^()]*\)\s*$", "", wanted)
    if base != wanted and base in haystack:
        return "extended", f"'{wanted[len(base):].strip()}' added to the listed title"
    return "missing", f"not found in {source}"


def metadata_mismatches(metadata: dict, entry: dict) -> list[str]:
    """Constant per-series metadata fields that differ from the registry."""
    return [
        f"project.metadata.{key} = {metadata.get(key)!r}, series.yaml says {entry.get(key)!r}"
        for key in METADATA_KEYS
        if entry.get(key) and metadata.get(key) != entry.get(key)
    ]
