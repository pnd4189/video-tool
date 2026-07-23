"""Music wiring for the cloud render path.

The cloud runner calls `init-job` without `--music`, so `inputs.music` has to be filled in
by the director. Without it the whole music bed is dropped at render time with no error.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Colab"))

import cloud_director as cd  # noqa: E402


def _job_with_music(tmp_path: Path, folder: str = "Music") -> Path:
    (tmp_path / folder).mkdir()
    (tmp_path / folder / "01-calm.mp3").write_bytes(b"x")
    return tmp_path


def test_seed_points_inputs_music_at_the_track_folder(tmp_path: Path) -> None:
    _job_with_music(tmp_path)
    data: dict = {}
    cd._seed_audio_story_defaults(tmp_path, data)
    assert data["inputs"]["music"] == "Music"


def test_seed_leaves_inputs_music_unset_without_tracks(tmp_path: Path) -> None:
    data: dict = {}
    cd._seed_audio_story_defaults(tmp_path, data)
    assert "music" not in data["inputs"]


def test_check_music_wiring_rejects_dropped_bed(tmp_path: Path) -> None:
    _job_with_music(tmp_path)
    with pytest.raises(cd.DirectorError, match="inputs.music is unset"):
        cd.check_music_wiring(tmp_path, {"inputs": {}})


def test_check_music_wiring_rejects_schedule_without_tracks(tmp_path: Path) -> None:
    with pytest.raises(cd.DirectorError, match="music_schedule"):
        cd.check_music_wiring(tmp_path, {"audio": {"music_schedule": [{"track": 1, "start": 0, "end": 10}]}})


def test_check_music_wiring_accepts_wired_job(tmp_path: Path) -> None:
    _job_with_music(tmp_path)
    cd.check_music_wiring(tmp_path, {"inputs": {"music": "Music"}})


def test_apply_creative_sets_input_overrides(tmp_path: Path) -> None:
    (tmp_path / "thumbs").mkdir()
    (tmp_path / "thumbs" / "15.jpg").write_bytes(b"x")
    data: dict = {}
    cd.apply_creative(tmp_path, data, {"inputs": {"intro_image": "thumbs/15.jpg"}}, tmp_path, tmp_path)
    assert data["inputs"]["intro_image"] == "thumbs/15.jpg"


def test_apply_creative_rejects_missing_input_override(tmp_path: Path) -> None:
    with pytest.raises(cd.DirectorError, match="intro_image"):
        cd.apply_creative(tmp_path, {}, {"inputs": {"intro_image": "nope.jpg"}}, tmp_path, tmp_path)
