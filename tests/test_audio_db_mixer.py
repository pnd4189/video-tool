from pathlib import Path

from videotool.core.job_spec import load_job
from videotool.core.timeline import compile_timeline
from videotool.render.commands import build_ffmpeg_command
from videotool.render.profiles import get_profile


def _command_for(job_yaml: str, tmp_path: Path) -> str:
    job_path = tmp_path / "job.yaml"
    job_path.write_text(job_yaml, encoding="utf-8")
    timeline = compile_timeline(load_job(job_path), job_path, duration=3.0)
    plan = build_ffmpeg_command(timeline, get_profile("libx264-balanced"), timeline.outputs[0])
    return " ".join(plan.command)


_BASE = """
version: 1
project:
  title: db-mixer
inputs:
  voice: voice.wav
  media_dir: media
  music: music.mp3
outputs:
  - preset: youtube-16x9
assets:
  policy: allow-missing-local
"""


def test_default_audio_keeps_sidechain_and_loudnorm(tmp_path: Path) -> None:
    command = _command_for(_BASE, tmp_path)
    assert "sidechaincompress" in command
    assert "loudnorm=I=-14:TP=-1:LRA=11" in command


def test_default_music_gain_is_minus_28_db(tmp_path: Path) -> None:
    command = _command_for(_BASE, tmp_path)
    assert "volume=-28.0dB" in command
    assert "volume=0.5" not in command


def test_duck_false_drops_sidechain_keeps_amix(tmp_path: Path) -> None:
    command = _command_for(_BASE + "audio:\n  duck: false\n", tmp_path)
    assert "sidechaincompress" not in command
    assert "amix" in command


def test_normalize_lufs_null_drops_loudnorm(tmp_path: Path) -> None:
    command = _command_for(_BASE + "audio:\n  normalize_lufs: null\n", tmp_path)
    assert "loudnorm" not in command


def test_voice_gain_db_applied_to_voice_branch(tmp_path: Path) -> None:
    command = _command_for(_BASE + "audio:\n  voice_gain_db: 3.0\n", tmp_path)
    assert "volume=3.0dB" in command


def test_custom_lufs_value_is_emitted(tmp_path: Path) -> None:
    command = _command_for(_BASE + "audio:\n  normalize_lufs: -16.0\n", tmp_path)
    assert "loudnorm=I=-16:TP=-1:LRA=11" in command
