"""Guards that stop a job before render time is spent on something silently wrong."""

from __future__ import annotations

from pathlib import Path

import yaml

from videotool.creative.rules import CreativeError

MUSIC_SUFFIXES = (".mp3", ".wav", ".m4a", ".flac", ".ogg")


def assert_timing_not_degraded(job_dir: Path, job_yaml: Path) -> None:
    """Stop when the images fell back to an even split they did not need to.

    An episode with no scene plan legitimately gets an even split — it warns and carries on. An
    even split in a folder that DOES hold a plan means something broke between the two, and
    finding that out after an hours-long render costs a whole slot. Deliberately asymmetric:
    missing data is a warning, contradicted data is a stop."""
    from videotool.core.scene_plan import find_scene_plan

    data = yaml.safe_load(Path(job_yaml).read_text(encoding="utf-8")) or {}
    source = (data.get("timing") or {}).get("source", "even")
    if source != "even":
        print(f"director: image timing = {source}")
        return
    plan = find_scene_plan(Path(job_dir))
    if plan is None:
        print("director: image timing = even split (no scene plan in this folder)")
        return
    raise RuntimeError(
        f"Timing fell back to an even split even though {plan.name} is present — the plan or "
        "the narration SRT could not be read. Fix that before spending a render slot."
    )


def check_music_wiring(job_dir: Path, data: dict) -> None:
    """Abort when the folder ships music tracks but the job would render silent.

    `services._stage_music` drops the whole bed (and any `audio.music_schedule`) unless
    `inputs.music` points at the tracks, so a missing key is a silent quality loss, not an error."""
    music = data.get("inputs", {}).get("music")
    if music:
        if not (Path(job_dir) / music).exists():
            raise CreativeError(f"inputs.music '{music}' does not exist in the job folder.")
        return
    if data.get("audio", {}).get("music_schedule"):
        raise CreativeError("audio.music_schedule is set but inputs.music is not — the bed would be dropped.")
    for name in ("Music", "music"):
        folder = Path(job_dir) / name
        if folder.is_dir() and any(p.suffix.lower() in MUSIC_SUFFIXES for p in folder.iterdir()):
            raise CreativeError(f"'{name}/' holds music tracks but inputs.music is unset — the bed would be dropped.")


def known_profiles() -> set[str]:
    from videotool.render.profiles import PROFILES

    return set(PROFILES)


def pre_render_checks(job_dir: Path, job_yaml: Path) -> None:
    """`videotool validate` plus what it omits: the encoder must be a real profile, every SFX cue
    and the overlay must exist inside the job folder, and the music bed must be wired."""
    from videotool.creative.prepare import run_cli

    run_cli(["validate", str(job_yaml)])
    data = yaml.safe_load(Path(job_yaml).read_text(encoding="utf-8")) or {}
    check_music_wiring(Path(job_dir), data)
    encoder = data.get("render", {}).get("encoder", "libx264-balanced")
    valid = known_profiles()
    if encoder not in valid:
        raise CreativeError(f"render.encoder '{encoder}' is not a known profile ({sorted(valid)}).")

    root = Path(job_dir).resolve()
    for cue in data.get("enhance", {}).get("sfx", {}).get("cues", []):
        path = (root / cue["file"]).resolve()
        if not path.is_relative_to(root):
            raise CreativeError(f"SFX cue escapes job folder: {cue['file']}")
        if not path.exists():
            raise CreativeError(f"SFX cue file missing: {cue['file']}")
    overlay = data.get("inputs", {}).get("particle_overlay")
    if overlay:
        path = (root / overlay).resolve()
        if not path.is_relative_to(root):
            raise CreativeError(f"particle_overlay escapes job folder: {overlay}")
        if not path.exists():
            raise CreativeError(f"particle_overlay file missing: {overlay}")
