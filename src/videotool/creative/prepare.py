"""Deterministic job preparation shared by the local and cloud render paths.

init-job -> harden (allow-missing-local, captions off, script) -> copy the provided SRT ->
detect intro/ending/CTA + creative input overrides -> storyboard auto (Image/ + Video/) ->
chapters-from-srt -> timing guard -> audio-story defaults (+ cloud render knobs).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from videotool.creative.checks import assert_timing_not_degraded
from videotool.creative.rules import CreativeError

AUDIO_EXTS = (".wav", ".mp3", ".m4a")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
FORCE_SEGMENTED_INLINE_CAP = 1  # schema forbids 0; 1 forces segmented for any >=2-scene job.
CLOUD_ENCODER = "h264_nvenc-capped"
TARGETS = ("cloud", "local")


def run_cli(args: list[str]) -> None:
    """Invoke the installed `videotool` console script (list-form: safe with Vietnamese paths)."""
    exe = shutil.which("videotool") or str(Path(sys.executable).with_name("videotool"))
    subprocess.run([exe, *args], check=True)


def write_job(job_yaml: Path, data: dict) -> None:
    job_yaml.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def read_job(job_yaml: Path) -> dict:
    return yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}


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


def ensure_job_yaml(job_dir: Path) -> Path:
    """Return a hardened `job.yaml`: a `_creative/job.yaml` seed, the folder's own, or init-job."""
    job_dir = Path(job_dir)
    job_yaml = job_dir / "job.yaml"
    seed = job_dir / "_creative" / "job.yaml"
    if seed.exists() and not job_yaml.exists():
        shutil.copy(seed, job_yaml)
    if not job_yaml.exists():
        run_cli(["init-job", str(job_dir), "--voice", detect_voice(job_dir).name, "--media", "media"])
    harden_job_yaml(job_yaml, job_dir)
    return job_yaml


def harden_job_yaml(job_yaml: Path, job_dir: Path) -> None:
    """init-job's licensed-only / srt-only defaults fail our flow: force allow-missing-local and
    captions off, point `inputs.script` at the script, and make sure the media dir exists."""
    data = read_job(job_yaml)
    data.setdefault("assets", {})["policy"] = "allow-missing-local"
    data.setdefault("captions", {})["mode"] = "off"
    inputs = data.setdefault("inputs", {})
    if not inputs.get("script"):
        script = detect_script(job_dir)
        if script is not None:
            inputs["script"] = script.name
    write_job(job_yaml, data)
    (Path(job_dir) / inputs.get("media_dir", "media")).mkdir(parents=True, exist_ok=True)


def copy_provided_srt(job_dir: Path) -> None:
    """Copy the user-provided QA SRT to outputs/captions.srt (the burn baseline). No whisper."""
    srts = sorted(job_dir.glob("*_vi_qa.srt")) or sorted(job_dir.glob("*.srt"))
    if not srts:
        return
    out = job_dir / "outputs"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(srts[0], out / "captions.srt")


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


def apply_input_overrides(job_dir: Path, data: dict, overrides: dict) -> None:
    """Job-relative input overrides from creative.yaml, for what the filename heuristics cannot
    resolve — e.g. a folder holding several `thumb*` candidates leaves `intro_image` unset."""
    for key, value in overrides.items():
        if not (job_dir / value).exists():
            raise CreativeError(f"creative inputs.{key} '{value}' does not exist in the job folder")
        data.setdefault("inputs", {})[key] = value


def seed_audio_story_defaults(job_dir: Path, data: dict, target: str = "cloud") -> None:
    """Audio-story channel defaults (no mood FX). `cloud` also pins the render knobs the render box
    needs: the NVENC encoder (the runner re-probes it) and the resumable segmented path."""
    enhance = data.setdefault("enhance", {})
    enhance.setdefault("visualizer", True)
    enhance.setdefault("subtitles", True)
    enhance.setdefault("subtitle_color", "yellow")

    inputs = data.setdefault("inputs", {})
    # Without `inputs.music` the whole music bed (and any music_schedule) is silently dropped.
    if not inputs.get("music"):
        music_dir = next((d for d in (job_dir / "Music", job_dir / "music") if d.is_dir()), None)
        if music_dir is not None:
            inputs["music"] = music_dir.name
    if not inputs.get("script"):
        script = detect_script(job_dir)
        if script is not None:
            inputs["script"] = script.name
    template = next(iter(sorted(job_dir.glob("*_DESCRIPTION_TEMPLATE.txt"))), None)
    if template and not inputs.get("description_template"):
        inputs["description_template"] = template.name

    if target == "cloud":
        render = data.setdefault("render", {})
        render["encoder"] = CLOUD_ENCODER
        render["max_inline_scenes"] = FORCE_SEGMENTED_INLINE_CAP


def prepare_job(job_dir: Path, input_overrides: dict | None = None, target: str = "cloud") -> dict:
    """Run the deterministic pre-steps and return the loaded job.yaml dict.

    The SRT is staged before the storyboard, not after: storyboard auto reads its times to pin each
    image to its narration and would silently fall back to an even split without it. The
    intro/ending images go in first for the same reason: storyboard auto builds the first/last 10s
    title-card scenes only from what job.yaml names at that moment."""
    if target not in TARGETS:
        raise CreativeError(f"prepare target must be one of {TARGETS}, not {target!r}")
    job_dir = Path(job_dir)
    job_yaml = ensure_job_yaml(job_dir)
    copy_provided_srt(job_dir)

    data = read_job(job_yaml)
    detect_intro_ending_cta(job_dir, data)
    apply_input_overrides(job_dir, data, input_overrides or {})
    write_job(job_yaml, data)

    images, videos = job_dir / "Image", job_dir / "Video"
    args = ["storyboard", "auto", str(job_yaml), "--images-dir", str(images if images.exists() else job_dir / "media")]
    if videos.exists():
        args += ["--videos-dir", str(videos)]
    run_cli(args)
    run_cli(["chapters-from-srt", str(job_yaml)])
    assert_timing_not_degraded(job_dir, job_yaml)

    data = read_job(job_yaml)
    seed_audio_story_defaults(job_dir, data, target)
    write_job(job_yaml, data)
    return data
