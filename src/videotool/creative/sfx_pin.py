"""`videotool creative sfx-pin`: turn quoted narration into exact SFX cue times.

The action word usually sits mid-sentence, so a cue's start places the SFX 1-3s early. Instead,
find the SRT cue that holds the quote and interpolate by character position:
`time = start + index / len(text) × (end − start)`. No re-transcription.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from videotool.creative.rules import CreativeError


def _fold(text: str) -> str:
    """Case- and composition-insensitive form: a capital at a sentence start or a differently
    composed diacritic must not make an otherwise identical quote miss."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).casefold()


def pin_time(quote: str, near: float, cues: list[tuple[float, float, str]]) -> float | None:
    """Interpolated time of `quote` inside the cue nearest to `near` that contains it."""
    wanted = _fold(quote)
    best: tuple[float, float] | None = None
    for start, end, text in cues:
        folded = _fold(text)
        index = folded.find(wanted)
        if index < 0:
            continue
        time = start + (end - start) * index / max(1, len(folded))
        distance = abs(start - near)
        if best is None or distance < best[0]:
            best = (distance, time)
    return round(best[1], 2) if best else None


def pin_all(picks: list[dict], cues: list[tuple[float, float, str]]) -> list[dict]:
    """Cue dicts {time, file, gain_db?} in the order given; raises listing every quote not found."""
    pinned, missing = [], []
    for pick in picks:
        time = pin_time(str(pick["quote"]), float(pick.get("near", 0)), cues)
        if time is None:
            missing.append(str(pick["quote"]))
            continue
        cue = {"time": time, "file": str(pick["file"])}
        if pick.get("gain_db") is not None:
            cue["gain_db"] = pick["gain_db"]
        if pick.get("note"):
            cue["note"] = str(pick["note"])
        pinned.append(cue)
    if missing:
        raise CreativeError("quote(s) not found in any SRT cue: " + "; ".join(repr(q) for q in missing))
    return sorted(pinned, key=lambda c: c["time"])


def _cue_line(indent: str, cue: dict) -> str:
    fields = [f"time: {cue['time']:.2f}", f"file: {cue['file']}"]
    if cue.get("gain_db") is not None:
        fields.append(f"gain_db: {cue['gain_db']}")
    note = f"  # {cue['note']}" if cue.get("note") else ""
    return f"{indent}- {{{', '.join(fields)}}}{note}"


def write_cues(creative_path: Path, cues: list[dict], pack: str | None = None) -> bool:
    """Replace `enhance.sfx.cues` in creative.yaml. Rewrites only that block when it exists, so the
    author's comments elsewhere survive; returns False when the whole file had to be re-dumped."""
    path = Path(creative_path)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s+)cues:\s*(#.*)?$", line)
        if not m or not _inside_sfx(lines, i, len(m.group(1))):
            continue
        indent = m.group(1)
        j = i + 1
        while j < len(lines) and _belongs_to_block(lines[j], len(indent)):
            j += 1
        while j > i + 1 and not lines[j - 1].strip():  # keep the blank lines that separate sections
            j -= 1
        block = [f"{indent}cues:"] + [_cue_line(indent + "  ", c) for c in cues]
        path.write_text("\n".join(lines[:i] + block + lines[j:]) + "\n", encoding="utf-8")
        _validate(path)
        return True
    data = yaml.safe_load(text) or {}
    sfx = data.setdefault("enhance", {}).setdefault("sfx", {})
    if pack and not sfx.get("pack"):
        sfx["pack"] = pack
    sfx["cues"] = [{k: v for k, v in c.items() if k != "note"} for c in cues]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return False


def _belongs_to_block(line: str, indent: int) -> bool:
    """A line of the `cues:` value: blank, indented deeper than the key, or a list item at the
    key's own indent (YAML allows both list styles)."""
    if not line.strip():
        return True
    depth = len(line) - len(line.lstrip())
    return depth > indent or (depth == indent and line.lstrip().startswith("- "))


def _inside_sfx(lines: list[str], index: int, indent: int) -> bool:
    """True when the `cues:` line at `index` sits directly under an `sfx:` key."""
    for k in range(index - 1, -1, -1):
        stripped = lines[k].strip()
        if not stripped or stripped.startswith("#"):
            continue
        depth = len(lines[k]) - len(lines[k].lstrip())
        if depth < indent:
            return stripped.startswith("sfx:")
    return False


def _validate(path: Path) -> None:
    try:
        yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - guards a malformed hand-edited file
        raise CreativeError(f"{path} is no longer valid YAML after writing the cues: {exc}") from exc
