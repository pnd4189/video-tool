import shutil
import subprocess
from pathlib import Path

import pytest

from videotool.core.errors import ValidationError
from videotool.core.media_probe import probe_media
from videotool.core.services import run_sfx
from videotool.render.sfx_mix import build_sfx_mix_command


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def test_build_sfx_mix_command_structure() -> None:
    cues = [(Path("sfx/a.wav"), 2.0, -3.0), (Path("sfx/b.wav"), 5.0, 0.0)]
    cmd = build_sfx_mix_command(Path("outputs/v.mp4"), cues, Path("out.mp4"), intro_offset=1.0)
    joined = " ".join(cmd)
    assert cmd.count("-i") == 3  # video + 2 sfx
    assert "adelay=3000:all=1" in joined  # (2.0 + 1.0) * 1000
    assert "adelay=6000:all=1" in joined  # (5.0 + 1.0) * 1000
    assert "amix=inputs=3:normalize=0:duration=first" in joined
    assert "alimiter=limit=0.95" in joined
    # video copied, audio re-encoded at 256k
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert "256k" in cmd


def test_build_sfx_mix_command_empty_cues_returns_none() -> None:
    assert build_sfx_mix_command(Path("v.mp4"), [], Path("out.mp4")) is None


def _write_min_job(tmp_path: Path, enhance: str = "") -> Path:
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        "version: 1\n"
        "project:\n  title: t\n"
        "inputs:\n  voice: voice.wav\n  media_dir: media\n"
        "outputs:\n  - preset: youtube-16x9\n"
        "assets:\n  policy: allow-missing-local\n" + enhance,
        encoding="utf-8",
    )
    return job_path


def test_run_sfx_noop_when_unset(tmp_path: Path) -> None:
    # No enhance.sfx -> returns [] before any validation or ffmpeg.
    assert run_sfx(_write_min_job(tmp_path)) == []


def test_run_sfx_rejects_file_outside_job_folder(tmp_path: Path) -> None:
    (tmp_path / "voice.wav").write_bytes(b"x")
    (tmp_path / "media").mkdir()
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "youtube-16x9.mp4").write_bytes(b"x")
    job_path = _write_min_job(
        tmp_path,
        enhance="enhance:\n  sfx:\n    cues:\n      - time: 1.0\n        file: ../evil.wav\n",
    )
    with pytest.raises(ValidationError, match="escapes the job folder"):
        run_sfx(job_path)


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg/ffprobe not installed")
def test_run_sfx_is_idempotent_via_master(tmp_path: Path) -> None:
    (tmp_path / "voice.wav").write_bytes(b"x")
    (tmp_path / "media").mkdir()
    sfx_dir = tmp_path / "sfx"
    sfx_dir.mkdir()
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=900:duration=0.4", "-c:a", "flac", str(sfx_dir / "hit.flac")],
        check=True,
    )
    out_dir = tmp_path / "outputs"
    out_dir.mkdir()
    mp4 = out_dir / "youtube-16x9.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=6",
         "-f", "lavfi", "-i", "sine=frequency=200:duration=6",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(mp4)],
        check=True,
    )
    job_path = _write_min_job(
        tmp_path,
        enhance="enhance:\n  sfx:\n    cues:\n      - time: 2.0\n        file: sfx/hit.flac\n",
    )
    assert run_sfx(job_path) == [mp4]
    master = tmp_path / ".videotool" / "sfx-master" / "youtube-16x9.mp4"
    assert master.exists()  # pre-SFX master preserved
    dur_after_first = probe_media(mp4).duration
    # Re-run: mixes from the clean master, so duration stays stable (no stacking / drift).
    assert run_sfx(job_path) == [mp4]
    assert probe_media(mp4).duration == pytest.approx(dur_after_first, abs=0.15)
