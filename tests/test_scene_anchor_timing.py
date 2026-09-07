from pathlib import Path

import pytest

from videotool.core.anchor_match import locate_anchors, normalize, parse_srt_cues
from videotool.core.scene_plan import find_scene_plan, parse_scene_plan
from videotool.core.scene_timing import solve_durations
from videotool.core.storyboard import build_even_split_storyboard

PLAN = """# Scene Plan

Genre: tiên hiệp · Images: 3 · Videos: 0 · Chapters: 2

| scene_id | chapter | source_anchor | scene_tag | characters | video? |
|---|---:|---|---|---|---|
| 001 | 41 | Trời vừa hửng sáng trên đỉnh núi | establishing | Lâm Ý |  |
| 002 | 41 | Hắn rút kiếm ra khỏi vỏ | action | Lâm Ý | ✓ |
| 003 | 42 | Bạch Nguyệt Lộ khẽ mỉm cười | dialogue | Bạch Nguyệt Lộ |  |
"""

# Same three scenes, only the three columns that matter, in a different order.
SIDECAR = """| source_anchor | scene_id | chapter |
|---|---|---|
| Trời vừa hửng sáng trên đỉnh núi | 1 | 41 |
| Hắn rút kiếm ra khỏi vỏ | 2 | 41 |
| Bạch Nguyệt Lộ khẽ mỉm cười | 3 | 42 |
"""

SRT = """1
00:00:00,000 --> 00:00:10,000
Chương 41: Mở đầu.

2
00:00:10,000 --> 00:00:20,000
Trời vừa hửng sáng trên đỉnh núi.

3
00:00:20,000 --> 00:00:30,000
Hắn rút kiếm ra khỏi vỏ.

4
00:00:30,000 --> 00:00:40,000
Chương 42: Gặp gỡ.

5
00:00:40,000 --> 00:00:50,000
Bạch Nguyệt Lộ khẽ mỉm cười.
"""


def _write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _images(directory: Path, scenes: list[int]) -> None:
    for number in scenes:
        (directory / f"____SCENE_{number:03}_____{number}.png").write_bytes(b"x")


# --- scene plan -------------------------------------------------------------------------


def test_plan_and_sidecar_parse_to_the_same_rows(tmp_path: Path) -> None:
    full = parse_scene_plan(_write(tmp_path, "scene-plan.md", PLAN))
    trimmed = parse_scene_plan(_write(tmp_path, "x_scene_anchors.md", SIDECAR))
    assert [(row.scene, row.chapter) for row in full] == [(1, 41), (2, 41), (3, 42)]
    assert [(row.scene, row.chapter) for row in trimmed] == [(1, 41), (2, 41), (3, 42)]
    assert [row.anchor for row in full] == [row.anchor for row in trimmed]


def test_visible_sidecar_wins_over_the_hidden_work_copy(tmp_path: Path) -> None:
    hidden = tmp_path / ".work"
    hidden.mkdir()
    _write(hidden, "scene-plan.md", PLAN)
    visible = _write(tmp_path, "ep_scene_anchors.md", SIDECAR)
    assert find_scene_plan(tmp_path) == visible


def test_hidden_copy_still_found_when_no_sidecar_exists(tmp_path: Path) -> None:
    hidden = tmp_path / ".work"
    hidden.mkdir()
    plan = _write(hidden, "scene-plan.md", PLAN)
    assert find_scene_plan(tmp_path) == plan


def test_a_folder_with_no_plan_at_all_reports_none(tmp_path: Path) -> None:
    assert find_scene_plan(tmp_path) is None


# --- anchor matching --------------------------------------------------------------------


def test_anchors_resolve_to_the_second_they_are_spoken(tmp_path: Path) -> None:
    rows = parse_scene_plan(_write(tmp_path, "scene-plan.md", PLAN))
    times, report = locate_anchors([row.anchor for row in rows], parse_srt_cues(SRT))
    assert report.exact == 3 and report.missing == 0
    assert times[0] == pytest.approx(10.0, abs=0.5)
    assert times[1] == pytest.approx(20.0, abs=0.5)
    assert times[2] == pytest.approx(40.0, abs=0.5)


def test_forward_cursor_picks_the_later_copy_of_a_repeated_sentence() -> None:
    srt = """1
00:00:00,000 --> 00:00:10,000
Hắn quay đầu lại.

2
00:00:10,000 --> 00:00:20,000
Một tiếng thét vang lên.

3
00:00:20,000 --> 00:00:30,000
Hắn quay đầu lại.
"""
    times, report = locate_anchors(
        ["Hắn quay đầu lại", "Một tiếng thét vang lên", "Hắn quay đầu lại"], parse_srt_cues(srt)
    )
    assert report.missing == 0
    # The third scene must land on the SECOND occurrence, not back at the first.
    assert times[2] > times[1] > times[0]


def test_a_reworded_anchor_still_matches_on_its_opening_words() -> None:
    srt = """1
00:00:00,000 --> 00:00:10,000
Ngọn gió lạnh thổi qua khe núi hẹp và tối.
"""
    times, report = locate_anchors(
        ["Ngọn gió lạnh thổi qua khe núi rất hẹp và tối om"], parse_srt_cues(srt)
    )
    assert report.prefix == 1 and report.missing == 0
    assert times[0] is not None


def test_an_anchor_that_is_nowhere_reports_missing() -> None:
    times, report = locate_anchors(["câu này không hề có trong lời kể"], parse_srt_cues(SRT))
    assert times == [None] and report.missing == 1


def test_normalize_keeps_vietnamese_diacritics() -> None:
    assert normalize('  "Lâm Ý"  đi   ') == "lâm ý đi"


# --- the solver -------------------------------------------------------------------------


def test_durations_total_the_window_exactly_and_respect_the_floor() -> None:
    kinds = ["image"] * 5
    # Three anchors bunched inside four seconds — far tighter than the floor.
    desired = [0.0, 1.0, 2.0, 3.0, 90.0]
    durations = solve_durations(kinds, [0.0] * 5, desired, (0.0, 100.0), floor=9.0)
    assert sum(durations) == 100.0
    assert min(durations) >= 9.0


def test_a_tight_cluster_borrows_locally_and_leaves_the_rest_alone() -> None:
    kinds = ["image"] * 6
    desired = [0.0, 1.0, 2.0, 60.0, 120.0, 180.0]
    durations = solve_durations(kinds, [0.0] * 6, desired, (0.0, 240.0), floor=9.0)
    starts = [sum(durations[:index]) for index in range(6)]
    # The scenes after the cluster keep the times their own anchors asked for.
    assert starts[3] == pytest.approx(60.0)
    assert starts[4] == pytest.approx(120.0)
    assert starts[5] == pytest.approx(180.0)


def test_video_clips_keep_their_exact_length() -> None:
    kinds = ["image", "video", "image"]
    durations = solve_durations(kinds, [0.0, 12.5, 0.0], [None, None, None], (0.0, 100.0))
    assert durations[1] == 12.5
    assert sum(durations) == 100.0


def test_an_unlocatable_scene_only_moves_itself() -> None:
    kinds = ["image"] * 4
    durations = solve_durations(
        kinds, [0.0] * 4, [0.0, None, 60.0, 90.0], (0.0, 120.0), floor=1.0
    )
    starts = [sum(durations[:index]) for index in range(4)]
    assert starts[2] == pytest.approx(60.0)  # neighbours untouched
    assert starts[3] == pytest.approx(90.0)
    assert 0.0 < starts[1] < 60.0  # the unknown one is spaced between them


def test_floor_shrinks_rather_than_failing_when_the_window_is_too_short() -> None:
    durations = solve_durations(["image"] * 10, [0.0] * 10, [None] * 10, (0.0, 20.0), floor=9.0)
    assert sum(durations) == 20.0
    assert all(duration > 0 for duration in durations)


# --- end to end -------------------------------------------------------------------------


def test_anchor_tier_places_images_at_their_own_words(tmp_path: Path) -> None:
    _images(tmp_path, [1, 2, 3])
    rows = parse_scene_plan(_write(tmp_path, "scene-plan.md", PLAN))
    scenes, timing = build_even_split_storyboard(
        tmp_path, 50.0, plan_rows=rows, cues=parse_srt_cues(SRT), floor=1.0
    )
    assert timing["source"] == "anchor"
    assert timing["anchors_matched"] == 3
    durations = [scene["duration"] for scene in scenes]
    assert sum(durations) == 50.0
    # Scene 2's anchor is spoken at 20s, so scene 1 must hold until then.
    assert durations[0] == pytest.approx(20.0, abs=0.5)


def test_no_plan_falls_back_to_an_even_split_and_says_so(tmp_path: Path, capsys) -> None:
    _images(tmp_path, [1, 2, 3, 4])
    scenes, timing = build_even_split_storyboard(tmp_path, 100.0)
    assert timing["source"] == "even"
    assert [scene["duration"] for scene in scenes] == [25.0] * 4
    assert "EVEN SPLIT" in capsys.readouterr().out


def test_images_without_scene_numbers_never_join_by_position(tmp_path: Path, capsys) -> None:
    for name in ("first.png", "second.png", "third.png"):
        (tmp_path / name).write_bytes(b"x")
    rows = parse_scene_plan(_write(tmp_path, "scene-plan.md", PLAN))
    _scenes, timing = build_even_split_storyboard(
        tmp_path, 50.0, plan_rows=rows, cues=parse_srt_cues(SRT)
    )
    assert timing["source"] == "even"
    assert "no usable scene number" in capsys.readouterr().out
