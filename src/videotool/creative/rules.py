"""Deterministic creative rules: SFX density/placement, music-cue cleanup, SRT parsing.

These are the contract the render box enforces on whatever an agent authored — a cue that breaks
one is dropped, not rejected, so `creative lint` replays the same functions to show what survives.
"""

from __future__ import annotations

import re
from pathlib import Path

# SFX density / placement rules (audio-story defaults, AGENTS.md).
SFX_MAX_CUES = 15            # floor; long episodes scale up via sfx_cue_cap
SFX_SECONDS_PER_CUE = 420.0  # one cue per ~7 min beyond the floor
SFX_MIN_SPACING_S = 30.0     # >= 30-60s between clustered cues
SFX_SKIP_HEAD_S = 30.0       # skip the first 30s (intro / CTA region)
SFX_SKIP_TAIL_S = 25.0       # skip the last 25s (outro / CTA region)
SFX_GAIN_DB = -11.0          # point-SFX sit -8..-15 dB under the un-ducked voice
SFX_SUFFIXES = (".wav", ".mp3", ".m4a", ".ogg")

_TIMESTAMP = re.compile(
    r"(\d\d):(\d\d):(\d\d)[,.](\d\d\d)\s*-->\s*(\d\d):(\d\d):(\d\d)[,.](\d\d\d)"
)


class CreativeError(RuntimeError):
    """Fatal creative/preparation error, with a message safe to print (no secrets)."""


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    """(start, end, text) per SRT cue, in file order; the cue text lines are joined by a space."""
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = _TIMESTAMP.search(block)
        if not m:
            continue
        g = m.groups()
        body = " ".join(block.splitlines()[2:]).strip()
        cues.append((_seconds(*g[:4]), _seconds(*g[4:]), body))
    return cues


def srt_cues(job_dir: Path) -> list[tuple[float, float, str]]:
    """Cues of the job's burn baseline `outputs/captions.srt`; empty when it is absent."""
    srt = Path(job_dir) / "outputs" / "captions.srt"
    if not srt.exists():
        return []
    return parse_srt(srt.read_text(encoding="utf-8"))


def voice_end(cues: list[tuple[float, float, str]]) -> float:
    """When the narration ends: the END of the last cue. Using the last cue's start instead cut
    the cap and the tail limit short by one cue length (Bình Thiên Chap 47 lost its last cue)."""
    return max((end for _, end, _ in cues), default=0.0)


def sfx_cue_cap(end_s: float) -> int:
    """How many cues an episode of this length may keep.

    A flat 15 was tuned for ~90-105 min episodes. The 15-chapter format (~2.6 h, from Bình Thiên
    Chap 31) hits that cap two thirds of the way in, and since cues are kept in time order the
    whole climax would end up silent. Scale with duration; never below the historical floor, so
    every episode up to ~105 min keeps its exact previous behaviour."""
    return max(SFX_MAX_CUES, int(end_s // SFX_SECONDS_PER_CUE))


def sfx_drop_reason(time: float, name: str, available: set[str], previous: float | None, end_s: float) -> str | None:
    """Why the box would drop this cue, or None when it keeps it (the cap is checked separately)."""
    if name not in available:
        return "file not in the SFX pack"
    if time < SFX_SKIP_HEAD_S:
        return f"inside the first {SFX_SKIP_HEAD_S:.0f}s (intro/CTA region)"
    if time > end_s - SFX_SKIP_TAIL_S:
        return f"inside the last {SFX_SKIP_TAIL_S:.0f}s (outro/CTA region)"
    if previous is not None and time - previous < SFX_MIN_SPACING_S:
        return f"{time - previous:.1f}s after the previous kept cue (< {SFX_MIN_SPACING_S:.0f}s)"
    return None


def filter_sfx_cues(raw: list, available: set[str], end_s: float) -> list[dict]:
    """Enforce the audio-story density: known files only, skip head/tail CTA regions, min spacing,
    hard cap on count. The author's placement is a suggestion; these caps are the contract.

    A cue's `gain_db` rides along when set, so a file reused later in the episode keeps its own
    level instead of inheriting the first cue's."""
    return [c for c, reason in explain_sfx_cues(raw, available, end_s) if reason is None]


def explain_sfx_cues(raw: list, available: set[str], end_s: float) -> list[tuple[dict, str | None]]:
    """Every parseable cue in time order with the reason the box drops it (None = kept)."""
    out: list[tuple[dict, str | None]] = []
    kept: list[float] = []
    cap = sfx_cue_cap(end_s)
    for c in sorted(raw, key=lambda c: c.get("time", 0)):
        try:
            time, name = float(c["time"]), str(c["file"])
        except (KeyError, TypeError, ValueError):
            continue
        entry = {"time": time, "file": name}
        if c.get("gain_db") is not None:
            entry["gain_db"] = c["gain_db"]
        if len(kept) >= cap:
            out.append((entry, f"over the cap of {cap} cues"))
            continue
        reason = sfx_drop_reason(time, name, available, kept[-1] if kept else None, end_s)
        if reason is None:
            kept.append(time)
        out.append((entry, reason))
    return out


def clean_music_cues(raw: list, ntracks: int, end_s: float) -> list[dict]:
    """Sort, clamp, and drop overlaps so the schedule satisfies job_spec's disjoint validator."""
    cues = []
    for c in raw:
        try:
            track, start, end = int(c["track"]), float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 1 <= track <= ntracks or end <= start:
            continue
        cues.append({"track": track, "start": max(0.0, start), "end": min(end, end_s)})
    cues.sort(key=lambda c: c["start"])
    disjoint: list[dict] = []
    for c in cues:
        if disjoint and c["start"] < disjoint[-1]["end"]:
            c["start"] = disjoint[-1]["end"]
        if c["end"] > c["start"]:
            disjoint.append(c)
    return disjoint
