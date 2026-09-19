"""Filename heuristics that find an episode's narration, script, title cards and CTA clips."""

from __future__ import annotations

from pathlib import Path

AUDIO_EXTS = (".wav", ".mp3", ".m4a")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def detect_voice(job_dir: Path) -> Path:
    """The narration audio: `voice.*` first, else the first audio file in the folder root."""
    job_dir = Path(job_dir)
    for ext in AUDIO_EXTS:
        candidate = job_dir / f"voice{ext}"
        if candidate.exists():
            return candidate
    matches = [p for p in sorted(job_dir.iterdir()) if p.suffix.lower() in AUDIO_EXTS]
    if not matches:
        raise FileNotFoundError(f"No voice audio ({', '.join(AUDIO_EXTS)}) found in {job_dir}")
    return matches[0]


def detect_script(job_dir: Path) -> Path | None:
    """The polished narration script: `*_vi*.txt` minus the prompt files, preferring `_vi_qa.txt`."""
    candidates = [p for p in sorted(Path(job_dir).glob("*_vi*.txt")) if "prompt" not in p.name.lower()]
    if not candidates:
        return None
    for suffix in ("_vi_qa.txt", "_vi.txt"):
        for p in candidates:
            if p.name.endswith(suffix):
                return p
    return candidates[0]


def title_card_candidates(job_dir: Path) -> tuple[list[Path], list[Path]]:
    """(thumbnail candidates, ending candidates) by filename/subfolder, anywhere under the job."""
    thumbs, ends = [], []
    for p in Path(job_dir).rglob("*"):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        name = (p.parent.name + " " + p.name).lower()
        if "thumb" in name:
            thumbs.append(p)
        if "end" in name or "outro" in name or "ảnh end" in name:
            ends.append(p)
    return thumbs, ends


def detect_intro_ending_cta(job_dir: Path, data: dict) -> None:
    """Filename heuristics; only set what is unambiguous (one candidate each)."""
    inputs = data.setdefault("inputs", {})
    thumbs, ends = title_card_candidates(job_dir)
    if len(thumbs) == 1 and not inputs.get("intro_image"):
        inputs["intro_image"] = str(thumbs[0].relative_to(job_dir))
    if len(ends) == 1 and not inputs.get("ending_image"):
        inputs["ending_image"] = str(ends[0].relative_to(job_dir))
    cta = job_dir / "CTA voice"
    if cta.exists():
        _set_if_present(inputs, "intro_cta", _first_match(cta, ("intro cta - with voice", "intro cta", "cta-intro")))
        _set_if_present(inputs, "outro_cta", _first_match(cta, ("outro cta - with voice", "outro cta", "cta-outro")))


def _first_match(folder: Path, stems: tuple[str, ...]) -> Path | None:
    """A CTA clip by stem, preferring an animated video (voice baked, e.g. ĐẠO SĨ's `cta-intro.mp4`)
    over a bare audio file — a plain `sorted()` would pick `cta-intro-voice.mp3` first because
    '-' < '.'. Video across all stems wins, then audio."""
    video = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".mp4", ".mov"))
    audio = sorted(p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    for group in (video, audio):
        for stem in stems:
            for p in group:
                if stem in p.name.lower():
                    return p
    return None


def _set_if_present(inputs: dict, key: str, path: Path | None) -> None:
    if path is not None and not inputs.get(key):
        inputs[key] = str(path)
