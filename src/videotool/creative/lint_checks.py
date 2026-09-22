"""Individual `creative lint` checks. Each returns (errors, warnings) as lists of strings."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from videotool.creative.checks import MUSIC_SUFFIXES
from videotool.creative.detect import title_card_candidates
from videotool.creative.rules import explain_sfx_cues
from videotool.creative.series import metadata_mismatches, title_status

CJK = re.compile(r"[一-鿿]")
DESCRIPTION_LIMIT = 5000
GAP_TOLERANCE_S = 1.0
SFX_MAX_REUSE = 2            # uses of one SFX file per episode (user rule, 2026-09-21)
SFX_CHAPTER_MIN_S = 300.0    # a chapter shorter than this may go without a cue
Found = tuple[list[str], list[str]]


def check_cjk(creative: dict, description: str) -> Found:
    project = json.dumps(creative.get("project") or {}, ensure_ascii=False)
    hits = sorted(set(CJK.findall(project + description)))
    return ([f"Chinese characters in project fields / description: {''.join(hits)}"] if hits else []), []


def check_series(creative: dict, entry: dict | None, prev_title: str | None = None) -> Found:
    if entry is None:
        return [], ["series not in series.yaml (new series? ask the user for channel, URL, author, title list)"]
    project = creative.get("project") or {}
    errors: list[str] = []
    warnings: list[str] = []
    title = project.get("title")
    if not title:
        errors.append("project.title is missing")
    else:
        status, detail = title_status(title, entry, prev_title)
        if status == "missing":
            errors.append(f"project.title is not in the series title list ({detail})")
        elif status == "extended":
            warnings.append(f"project.title extends a listed title: {detail} — confirm the user asked for it")
        elif status == "unverified":
            warnings.append(f"title not checked: {detail}")
    errors += metadata_mismatches(project.get("metadata") or {}, entry)
    return errors, warnings


def check_bitrate_cap(creative: dict) -> Found:
    """`render.bitrate_cap` must name a real encoder variant: the box maps it onto
    `<profile>-<cap>` and aborts before any GPU time when that profile does not exist
    (CHAP 3 pinned '2800k', which is the default ceiling and has no variant)."""
    cap = (creative.get("render") or {}).get("bitrate_cap")
    if not cap:
        return [], []
    from videotool.render.profiles import PROFILES

    caps = sorted({p.rsplit("-", 1)[-1] for p in PROFILES if re.fullmatch(r"\d+k", p.rsplit("-", 1)[-1])})
    if not any(p.endswith(f"-{cap}") for p in PROFILES):
        return ([f"render.bitrate_cap '{cap}' has no encoder profile (valid caps: {', '.join(caps)}; "
                 "the default ceiling needs no cap) — drop the line or use one of those"], [])
    return [], []


def check_description(description: str | None) -> Found:
    if description is None:
        return [], ["no *_DESCRIPTION_TEMPLATE.txt in the job root — package will not write description.txt"]
    errors: list[str] = []
    body = description.split("==== TAGS")[0].rstrip()
    if len(body) >= DESCRIPTION_LIMIT:
        errors.append(f"description before '==== TAGS' is {len(body)} chars (YouTube limit {DESCRIPTION_LIMIT})")
    leftover = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", description)))
    if leftover:
        errors.append(f"description still holds placeholders: {', '.join(leftover)}")
    return errors, []


def check_sfx(creative: dict, pack_dir: Path, end_s: float) -> tuple[list[str], list[str], list[tuple[dict, str | None]]]:
    sfx = ((creative.get("enhance") or {}).get("sfx") or {})
    cues = sfx.get("cues") or []
    if not cues:
        return [], ["no SFX cues — audio-story episodes carry one-shot SFX by default"], []
    pack_error = []
    if not sfx.get("pack"):
        # The render box does not read series.yaml: without a pack it guesses one from keywords.
        pack_error = [f"enhance.sfx.pack is missing — write `pack: {pack_dir.name}` so the render box "
                      "does not have to guess the pack"]
    available = {p.name for p in pack_dir.glob("*")} if pack_dir.is_dir() else set()
    raw, unusable = [], []
    for cue in cues:
        try:
            time_s = float(cue.get("time"))
        except (TypeError, ValueError):
            # explain_sfx_cues skips these, so without this they would vanish from the report too.
            unusable.append(f"SFX cue {cue!r} has no usable numeric `time` — it is dropped silently")
            continue
        raw.append({"time": time_s, "file": Path(str(cue.get("file", ""))).name, "gain_db": cue.get("gain_db")})
    explained = explain_sfx_cues(raw, available, end_s)
    errors = pack_error + unusable + [f"SFX {c['file']} @ {c['time']:.2f}s: not in pack {pack_dir.name}"
                                      for c, r in explained if r == "file not in the SFX pack"]
    warnings = [f"SFX {c['file']} @ {c['time']:.2f}s will be DROPPED: {r}" for c, r in explained
                if r and r != "file not in the SFX pack"]
    return errors, warnings, explained


def check_sfx_spread(explained: list[tuple[dict, str | None]], chapters: list[dict], end_s: float) -> tuple[list[str], list[str], list[int]]:
    """Kept cues per chapter, a chapter left without SFX, a file used too often.

    ĐẠO SĨ Chap 22 kept every cue inside the first 12 minutes of 82 and nothing flagged it; the
    per-file limit is the user's rule for every episode (2026-09-21)."""
    kept = [c for c, reason in explained if reason is None]
    errors = [f"SFX {name} is used {n} times — at most {SFX_MAX_REUSE} per episode"
              for name, n in Counter(c["file"] for c in kept).items() if n > SFX_MAX_REUSE]
    spans = sorted((float(c["start"]), str(c.get("title", ""))) for c in chapters)
    counts: list[int] = []
    for i, (start, title) in enumerate(spans):
        stop = spans[i + 1][0] if i + 1 < len(spans) else end_s
        counts.append(sum(1 for c in kept if start <= c["time"] < stop))
        if kept and counts[-1] == 0 and stop - start >= SFX_CHAPTER_MIN_S:
            errors.append(f"no SFX kept in {title or f'chapter {i + 1}'} ({start:.0f}s–{stop:.0f}s) — "
                          "spread the cues over the whole episode")
    return errors, [], counts


def _track_count(job_dir: Path, music: str | None) -> list[str]:
    folder = job_dir / (music or "Music")
    return sorted(p.stem for p in folder.iterdir() if p.suffix.lower() in MUSIC_SUFFIXES) if folder.is_dir() else []


def check_music(creative: dict, job_dir: Path, music: str | None, end_s: float) -> Found:
    cues = ((creative.get("audio") or {}).get("music_schedule")) or []
    if not cues:
        return [], ["no audio.music_schedule — all tracks play concatenated and looped"]
    tracks = _track_count(job_dir, music)
    errors: list[str] = []
    for c in cues:
        track = c.get("track")
        if isinstance(track, int) and not 1 <= track <= len(tracks):
            errors.append(f"music track {track} out of range (Music/ has {len(tracks)} tracks)")
        elif isinstance(track, str) and not any(track in stem for stem in tracks):
            errors.append(f"music track '{track}' matches no file in Music/")
    spans = []
    for c in cues:
        try:
            spans.append((float(c.get("start", 0)), float(c.get("end", 0))))
        except (TypeError, ValueError):
            errors.append(f"music cue {c!r}: start/end must be numbers of seconds")
    if not spans:
        return errors, []
    spans.sort()
    if spans[0][0] > GAP_TOLERANCE_S:
        errors.append(f"music starts at {spans[0][0]:.2f}s — the first {spans[0][0]:.0f}s have no track")
    for (_, prev_end), (start, _) in zip(spans, spans[1:]):
        if start - prev_end > GAP_TOLERANCE_S:
            errors.append(f"music gap {prev_end:.2f}s → {start:.2f}s")
    if spans[-1][1] < end_s - GAP_TOLERANCE_S:
        errors.append(f"music ends at {spans[-1][1]:.2f}s but the narration runs to {end_s:.2f}s")
    return errors, []


def check_title_cards(job_dir: Path, creative: dict, inputs: dict) -> Found:
    warnings: list[str] = []
    thumbs, ends = title_card_candidates(job_dir)
    override = (creative.get("inputs") or {}).get("intro_image")
    if len(thumbs) > 1 and not override:
        names = ", ".join(p.name for p in thumbs)
        warnings.append(f"{len(thumbs)} thumbnail candidates ({names}) and no inputs.intro_image override — "
                        "the episode gets NO intro card")
    elif not inputs.get("intro_image"):
        warnings.append("no intro_image — the first 10s have no title card")
    if not inputs.get("ending_image"):
        warnings.append(f"no ending_image ({len(ends)} candidate(s)) — the last 10s have no ending card")
    return [], warnings


def check_parallax(creative: dict, data: dict, stills: int) -> Found:
    enhance = creative.get("enhance") or {}
    if not (data.get("enhance") or {}).get("parallax") or stills == 0:
        return [], []
    if enhance.get("parallax_on_box"):
        return [], [f"{stills} still(s) will get depth parallax ON THE BOX (hours) — parallax_on_box is set"]
    return [f"enhance.parallax is on but {stills} story still(s) have no clip in Parallax/ — "
            "the box aborts; upload the clips or ask the user"], []
