"""Music wiring for the cloud render path.

The cloud runner calls `init-job` without `--music`, so `inputs.music` has to be filled in
by the director. Without it the whole music bed is dropped at render time with no error.
"""

from __future__ import annotations

import json
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


def test_apply_creative_passes_parallax_through(tmp_path: Path) -> None:
    # Episodes without a pre-rendered Parallax/ folder request depth-parallax via creative.yaml.
    data: dict = {}
    cd.apply_creative(tmp_path, data, {"enhance": {"parallax": True}}, tmp_path, tmp_path)
    assert data["enhance"]["parallax"] is True


def test_sfx_cue_cap_keeps_the_historical_floor_for_normal_episodes() -> None:
    # <= ~105 min episodes must behave exactly as before (flat 15).
    assert cd._sfx_cue_cap(2700.0) == 15   # 45 min
    assert cd._sfx_cue_cap(6300.0) == 15   # 105 min


def test_sfx_cue_cap_scales_with_a_15_chapter_episode() -> None:
    # 158 min (Bình Thiên Chap 31): a flat 15 would stop at ~2/3 of the runtime and leave the
    # climax silent, because cues are kept in time order.
    assert cd._sfx_cue_cap(9516.0) == 22


def test_filter_sfx_cues_keeps_late_cues_on_a_long_episode() -> None:
    raw = [{"time": 60.0 + i * 400.0, "file": "a.mp3"} for i in range(21)]
    kept = cd._filter_sfx_cues(raw, {"a.mp3"}, 9516.0)
    assert len(kept) == 21
    assert kept[-1]["time"] > 8000.0


def test_reused_sfx_file_keeps_its_own_gain(tmp_path: Path, monkeypatch) -> None:
    # A file used twice in one episode used to inherit the FIRST cue's gain_db, because the lookup
    # matched on filename alone.
    pack = tmp_path / "pack" / "binh-thien"
    pack.mkdir(parents=True)
    (pack / "boom.mp3").write_bytes(b"x")
    job = tmp_path / "job"
    (job / "outputs").mkdir(parents=True)
    # voice_end comes from the last cue START, so the SRT must run past the cue times.
    (job / "outputs" / "captions.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nmo dau\n\n2\n00:10:00,000 --> 00:10:02,000\nket\n",
        encoding="utf-8",
    )
    data: dict = {}
    creative = {
        "enhance": {
            "sfx": {
                "pack": "binh-thien",
                "cues": [
                    {"time": 100.0, "file": "boom.mp3", "gain_db": -18},
                    {"time": 400.0, "file": "boom.mp3", "gain_db": -10},
                ],
            }
        }
    }
    cd.apply_creative(job, data, creative, tmp_path / "pack", tmp_path / "overlays")
    assert [c["gain_db"] for c in data["enhance"]["sfx"]["cues"]] == [-18, -10]


def test_renumber_srt_chapters_rewrites_burn_baseline(tmp_path) -> None:
    # The burned subtitles come from outputs/captions.srt, so an episode whose source SRT numbers
    # chapters per-file ("Chương 1") has to be renumbered BEFORE the render — afterwards only the
    # description can be corrected, never the pixels.
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "captions.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nChương 1: Khách viếng thăm.\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nmột câu thoại nhắc Chương 1 nhưng không phải tiêu đề\n\n"
        "3\n00:10:00,000 --> 00:10:02,000\n\" Chương 33: Dị biến (4).\n",
        encoding="utf-8",
    )
    replaced = cd._renumber_srt_chapters(tmp_path, {1: 77, 33: 78})
    text = (outputs / "captions.srt").read_text(encoding="utf-8")

    assert replaced == 2
    assert "Chương 77: Khách viếng thăm." in text
    assert "Chương 78: Dị biến (4)." in text
    assert "Chương 1:" not in text and "Chương 33:" not in text
    assert "nhắc Chương 1 nhưng" in text  # no trailing colon -> left alone


def test_renumber_srt_chapters_fails_loudly_on_unknown_number(tmp_path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nChương 1: A.\n", encoding="utf-8")
    with pytest.raises(cd.DirectorError):
        cd._renumber_srt_chapters(tmp_path, {5: 90})


def test_write_chapters_overrides_the_srt_derived_list(tmp_path) -> None:
    # chapters-from-srt can only emit the chapter headings; the description format also lists
    # story beats between them, so creative.yaml gets the final say.
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "chapters.json").write_text('[{"start": 0.0, "title": "cũ"}]', encoding="utf-8")
    cd._write_chapters(tmp_path, [
        {"start": 0, "title": "Chương 77: Khách viếng thăm đêm tuyết (1)"},
        {"start": 697.5, "title": " Ổ khóa hóa chìa khóa "},
    ])
    written = json.loads((tmp_path / "outputs" / "chapters.json").read_text(encoding="utf-8"))
    assert written == [
        {"start": 0.0, "title": "Chương 77: Khách viếng thăm đêm tuyết (1)"},
        {"start": 697.5, "title": "Ổ khóa hóa chìa khóa"},
    ]
