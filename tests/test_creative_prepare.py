"""Shared job preparation (local vs cloud) and the SFX rules the render box enforces."""

from __future__ import annotations

from pathlib import Path

import pytest

from videotool.creative import prepare as prep
from videotool.creative import rules
from videotool.creative.rules import CreativeError

SRT = """1
00:00:00,000 --> 00:00:04,000
Chương 1: Mở đầu

2
00:00:04,000 --> 00:02:00,500
Một đoạn dài.

3
00:02:00,500 --> 00:02:10,000
Câu cuối cùng
kéo dài hai dòng.
"""


def test_cloud_target_pins_the_render_box_knobs(tmp_path: Path) -> None:
    data: dict = {}
    prep.seed_audio_story_defaults(tmp_path, data, "cloud")
    assert data["render"] == {"encoder": "h264_nvenc-capped", "max_inline_scenes": 1}
    assert data["enhance"]["subtitle_color"] == "yellow"


def test_local_target_leaves_the_encoder_to_the_job(tmp_path: Path) -> None:
    data: dict = {"render": {"encoder": "libx264-balanced-capped-2500k"}}
    prep.seed_audio_story_defaults(tmp_path, data, "local")
    assert data["render"] == {"encoder": "libx264-balanced-capped-2500k"}
    assert data["enhance"]["subtitles"] is True


def test_unknown_target_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CreativeError, match="target"):
        prep.prepare_job(tmp_path, target="kaggle")


def test_parse_srt_keeps_start_end_and_joined_text() -> None:
    cues = rules.parse_srt(SRT)
    assert cues[0] == (0.0, 4.0, "Chương 1: Mở đầu")
    assert cues[2] == (120.5, 130.0, "Câu cuối cùng kéo dài hai dòng.")


def test_voice_end_is_the_end_of_the_last_cue() -> None:
    assert rules.voice_end(rules.parse_srt(SRT)) == 130.0
    assert rules.voice_end([]) == 0.0


def test_a_cue_near_the_end_survives_when_measured_from_the_real_end() -> None:
    # Bình Thiên Chap 47: the last cue starts at 7558.08 and ends at 7564.14. Measured from the
    # start, the cap was 17 and the 18th cue was cut; measured from the end it is 18.
    raw = [{"time": 60.0 + 400.0 * i, "file": "a.mp3"} for i in range(18)]
    assert len(rules.filter_sfx_cues(raw, {"a.mp3"}, 7558.08)) == 17
    assert len(rules.filter_sfx_cues(raw, {"a.mp3"}, 7564.14)) == 18


def test_explain_sfx_cues_names_every_drop_reason() -> None:
    raw = [
        {"time": 10.0, "file": "a.mp3"},    # head
        {"time": 100.0, "file": "a.mp3"},   # kept
        {"time": 115.0, "file": "a.mp3"},   # spacing
        {"time": 200.0, "file": "zz.mp3"},  # unknown file
        {"time": 990.0, "file": "a.mp3"},   # tail
    ]
    reasons = [r for _, r in rules.explain_sfx_cues(raw, {"a.mp3"}, 1000.0)]
    assert reasons[1] is None
    assert "first 30s" in reasons[0]
    assert "previous kept cue" in reasons[2]
    assert "not in the SFX pack" in reasons[3]
    assert "last 25s" in reasons[4]


def test_explain_sfx_cues_reports_the_cap() -> None:
    raw = [{"time": 60.0 + 40.0 * i, "file": "a.mp3"} for i in range(17)]
    reasons = [r for _, r in rules.explain_sfx_cues(raw, {"a.mp3"}, 1000.0)]
    assert reasons.count(None) == 15
    assert all("cap of 15" in r for r in reasons[15:])
