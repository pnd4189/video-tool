import shutil
import subprocess
from pathlib import Path

import pytest

from videotool.core.errors import RenderError
from videotool.core.media_probe import probe_media
from videotool.render.music_loop import (
    MAX_PLAYS,
    prepare_seamless_music,
)


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


pytestmark = pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg/ffprobe not installed")


def _synth_tone(path: Path, duration: float, frequency: int = 440) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration:.3f}",
            "-c:a", "flac", str(path),
        ],
        check=True,
    )


def test_trim_when_music_longer_than_target(tmp_path: Path) -> None:
    music = tmp_path / "music.flac"
    _synth_tone(music, duration=10.0)

    output = prepare_seamless_music(music, target_duration=4.0, workspace_root=tmp_path / "ws")

    assert output.exists()
    meta = probe_media(output)
    assert meta.duration is not None
    assert abs(meta.duration - 4.0) < 0.2


def test_loop_when_music_shorter_than_target(tmp_path: Path) -> None:
    music = tmp_path / "music.flac"
    _synth_tone(music, duration=2.0)

    output = prepare_seamless_music(music, target_duration=7.0, workspace_root=tmp_path / "ws")

    assert output.exists()
    meta = probe_media(output)
    assert meta.duration is not None
    assert abs(meta.duration - 7.0) < 0.3


def test_rejects_non_positive_target(tmp_path: Path) -> None:
    music = tmp_path / "music.flac"
    _synth_tone(music, duration=2.0)
    with pytest.raises(RenderError, match="target_duration must be positive"):
        prepare_seamless_music(music, target_duration=0.0, workspace_root=tmp_path / "ws")


def test_rejects_when_loop_count_exceeds_cap(tmp_path: Path) -> None:
    music = tmp_path / "music.flac"
    _synth_tone(music, duration=1.0)
    huge_target = float(MAX_PLAYS * 2)
    with pytest.raises(RenderError, match="Music track too short"):
        prepare_seamless_music(music, target_duration=huge_target, workspace_root=tmp_path / "ws")
