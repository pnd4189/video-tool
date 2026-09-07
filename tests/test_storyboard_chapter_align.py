from pathlib import Path

import pytest

from videotool.core.chapter_timing import chapter_starts_from_srt
from videotool.core.storyboard import (
    asset_scene_numbers,
    build_even_split_storyboard,
    parse_prompt_chapters,
)


PROMPTS = """=== CHƯƠNG 421 ===

--- SCENE 001 ---
Subject: a
Action: a

--- SCENE 002 ---
Action: b

=== CHƯƠNG 422 ===

--- SCENE 003 ---
Action: c

--- SCENE 004 ---
Action: d

--- SCENE 005 ---
Action: e
"""

SRT = """1
00:00:00,000 --> 00:00:03,000
Chương 421: Không muốn.

2
00:00:03,500 --> 00:00:06,000
Giữa chương.

3
00:01:40,000 --> 00:01:44,000
Chương 422: Hắc ý.
"""


def _images(directory: Path, scenes: list[int]) -> None:
    for number in scenes:
        (directory / f"____SCENE_{number:03}_____{number}.png").write_bytes(b"x")


def test_parse_prompt_chapters_maps_scenes_to_chapters(tmp_path: Path) -> None:
    prompts = tmp_path / "x_image_prompts.txt"
    prompts.write_text(PROMPTS, encoding="utf-8")
    assert parse_prompt_chapters(prompts) == {1: 421, 2: 421, 3: 422, 4: 422, 5: 422}


def test_parse_prompt_chapters_empty_without_separators(tmp_path: Path) -> None:
    prompts = tmp_path / "x_image_prompts.txt"
    prompts.write_text("--- SCENE 001 ---\nAction: a\n", encoding="utf-8")
    assert parse_prompt_chapters(prompts) == {}


def test_chapter_starts_keeps_markers_under_the_youtube_gap() -> None:
    assert chapter_starts_from_srt(SRT) == {421: 0.0, 422: 100.0}


def test_asset_scene_numbers_reads_the_filename_and_survives_gaps(tmp_path: Path) -> None:
    _images(tmp_path, [1, 2, 4])
    paths = sorted(tmp_path.iterdir())
    assert asset_scene_numbers(paths) == [1, 2, 4]
    assert asset_scene_numbers([tmp_path / "plain.png"]) is None


def test_chapter_alignment_gives_each_chapter_its_narration_span(tmp_path: Path) -> None:
    _images(tmp_path, [1, 2, 3, 4, 5])
    scenes, _ = build_even_split_storyboard(
        tmp_path,
        200.0,
        prompt_chapters={1: 421, 2: 421, 3: 422, 4: 422, 5: 422},
        chapter_starts={421: 0.0, 422: 100.0},
    )
    durations = [scene["duration"] for scene in scenes]
    # Chapter 421 holds 2 images across its 100s; chapter 422 holds 3 across the other 100s.
    assert durations[:2] == [50.0, 50.0]
    assert all(abs(duration - 100.0 / 3) <= 0.001 for duration in durations[2:])
    assert sum(durations) == pytest.approx(200.0)
    # The chapter boundary is the point of the whole tier: image 3 must start exactly at it.
    assert sum(durations[:2]) == 100.0


def test_alignment_differs_from_the_even_split_it_replaces(tmp_path: Path) -> None:
    _images(tmp_path, [1, 2, 3, 4, 5])
    even, _ = build_even_split_storyboard(tmp_path, 200.0)
    assert [scene["duration"] for scene in even] == [40.0] * 5


def test_a_missing_scene_does_not_shift_later_images(tmp_path: Path) -> None:
    # Scene 2's image failed to generate; scenes 3-5 must still land in chapter 422.
    _images(tmp_path, [1, 3, 4, 5])
    scenes, _ = build_even_split_storyboard(
        tmp_path,
        200.0,
        prompt_chapters={1: 421, 2: 421, 3: 422, 4: 422, 5: 422},
        chapter_starts={421: 0.0, 422: 100.0},
    )
    durations = [scene["duration"] for scene in scenes]
    assert durations[0] == 100.0
    assert sum(durations) == pytest.approx(200.0)


def test_intro_and_ending_overlays_shrink_the_aligned_window(tmp_path: Path) -> None:
    _images(tmp_path, [1, 2, 3, 4, 5])
    intro = tmp_path / "thumb.png"
    ending = tmp_path / "end.png"
    for path in (intro, ending):
        path.write_bytes(b"x")
    scenes, _ = build_even_split_storyboard(
        tmp_path,
        200.0,
        intro_image=intro,
        ending_image=ending,
        prompt_chapters={1: 421, 2: 421, 3: 422, 4: 422, 5: 422},
        chapter_starts={421: 0.0, 422: 100.0},
    )
    assert sum(scene["duration"] for scene in scenes) == pytest.approx(200.0)
    # Intro card, five story scenes, ending card.
    assert len(scenes) == 7
    assert scenes[0]["duration"] == 10.0 and scenes[-1]["duration"] == 10.0
    # Chapter 421 keeps 90s (100s minus the intro overlay), chapter 422 keeps 90s.
    assert scenes[1]["duration"] == 45.0


def test_unmarked_scenes_fall_back_to_the_even_split(tmp_path: Path, capsys) -> None:
    _images(tmp_path, [1, 2, 3, 4, 5])
    scenes, _ = build_even_split_storyboard(tmp_path, 200.0, prompt_chapters={}, chapter_starts=None)
    assert [scene["duration"] for scene in scenes] == [40.0] * 5


def test_chapter_numbers_absent_from_the_srt_are_ignored(tmp_path: Path) -> None:
    _images(tmp_path, [1, 2, 3, 4, 5])
    # Chapter 999 exists in the prompts but not in the narration; those scenes fall back to
    # the chapter being narrated at their provisional position instead of breaking the run.
    scenes, _ = build_even_split_storyboard(
        tmp_path,
        200.0,
        prompt_chapters={1: 421, 2: 999, 3: 422, 4: 422, 5: 422},
        chapter_starts={421: 0.0, 422: 100.0},
    )
    assert sum(scene["duration"] for scene in scenes) == pytest.approx(200.0)


def test_backwards_separator_cannot_rewind_the_timeline(tmp_path: Path) -> None:
    _images(tmp_path, [1, 2, 3, 4, 5])
    scenes, _ = build_even_split_storyboard(
        tmp_path,
        200.0,
        prompt_chapters={1: 421, 2: 422, 3: 421, 4: 422, 5: 422},
        chapter_starts={421: 0.0, 422: 100.0},
    )
    assert sum(scene["duration"] for scene in scenes) == pytest.approx(200.0)
    assert all(scene["duration"] > 0 for scene in scenes)
