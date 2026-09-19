"""`creative sfx-pin`: quote -> character-interpolated cue time -> creative.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from videotool.creative.rules import CreativeError
from videotool.creative.sfx_pin import pin_all, pin_time, write_cues

CUES = [
    (100.0, 110.0, "Một tiếng nổ vang lên giữa trời"),
    (500.0, 504.0, "abcdefghij tiếng nổ"),
    (900.0, 910.0, "không liên quan"),
]


def test_time_is_interpolated_by_character_position() -> None:
    # "vang" starts at index 13 of a 31-char cue spanning 10s.
    assert pin_time("vang lên", 100.0, CUES) == round(100.0 + 10.0 * 13 / 31, 2)


def test_the_cue_nearest_to_near_wins() -> None:
    assert pin_time("tiếng nổ", 480.0, CUES) == round(500.0 + 4.0 * 11 / 19, 2)
    assert pin_time("tiếng nổ", 90.0, CUES) == round(100.0 + 10.0 * 4 / 31, 2)


def test_a_capitalised_sentence_start_still_matches() -> None:
    assert pin_time("một tiếng", 100.0, CUES) == 100.0


def test_missing_quotes_are_all_listed() -> None:
    picks = [{"quote": "không có", "near": 1, "file": "a.mp3"}, {"quote": "cũng không", "near": 1, "file": "b.mp3"}]
    with pytest.raises(CreativeError, match="không có.*cũng không"):
        pin_all(picks, CUES)


def test_pin_all_sorts_and_keeps_gain() -> None:
    picks = [{"quote": "không liên quan", "near": 900, "file": "b.mp3"},
             {"quote": "Một tiếng", "near": 100, "file": "a.mp3", "gain_db": -12, "note": "boom"}]
    assert pin_all(picks, CUES) == [
        {"time": 100.0, "file": "a.mp3", "gain_db": -12, "note": "boom"},
        {"time": 900.0, "file": "b.mp3"},
    ]


CREATIVE = """# header comment
project:
  title: "T"   # keep me

enhance:
  sfx:
    pack: binh-thien
    # cue comment kept above
    cues:
      - {time: 1.0, file: old.mp3}
      - {time: 2.0, file: old.mp3}

audio:
  music_schedule: []
"""


def test_write_cues_replaces_only_the_cues_block(tmp_path: Path) -> None:
    path = tmp_path / "creative.yaml"
    path.write_text(CREATIVE, encoding="utf-8")
    assert write_cues(path, [{"time": 42.5, "file": "new.mp3", "gain_db": -9, "note": "đòn chém"}]) is True
    text = path.read_text(encoding="utf-8")
    assert "# header comment" in text and "# keep me" in text and "# cue comment kept above" in text
    assert "old.mp3" not in text and "# đòn chém" in text
    data = yaml.safe_load(text)
    assert data["enhance"]["sfx"]["cues"] == [{"time": 42.5, "file": "new.mp3", "gain_db": -9}]
    assert data["audio"] == {"music_schedule": []}


def test_write_cues_creates_the_block_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "creative.yaml"
    path.write_text("project: {title: T}\n", encoding="utf-8")
    assert write_cues(path, [{"time": 3.0, "file": "a.mp3", "note": "x"}], pack="dao-si") is False
    sfx = yaml.safe_load(path.read_text(encoding="utf-8"))["enhance"]["sfx"]
    assert sfx == {"pack": "dao-si", "cues": [{"time": 3.0, "file": "a.mp3"}]}
