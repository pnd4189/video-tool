from pathlib import Path

import yaml

from videotool.cli.storyboard_commands import auto_storyboard
from videotool.core.job_spec import JobSpec
from videotool.core.storyboard import (
    INTRO_SECONDS,
    MOTION_CYCLE,
    OUTRO_SECONDS,
    build_even_split_storyboard,
    discover_scene_images,
    interleave_media_by_story_order,
    natural_sort_key,
)


def test_natural_sort_orders_numeric_runs() -> None:
    names = ["scene_10.jpg", "scene_2.jpg", "scene_1.jpg"]
    ordered = sorted(names, key=natural_sort_key)
    assert ordered == ["scene_1.jpg", "scene_2.jpg", "scene_10.jpg"]


def test_discover_scene_images_is_naming_agnostic(tmp_path: Path) -> None:
    for name in ["frame-12.jpeg", "001.png", "002.png", "010.png", "notes.txt"]:
        (tmp_path / name).write_bytes(b"x")
    found = [path.name for path in discover_scene_images(tmp_path)]
    assert found == ["001.png", "002.png", "010.png", "frame-12.jpeg"]


def test_even_split_sums_to_voice_duration(tmp_path: Path) -> None:
    for name in ["a1.png", "a2.png", "a3.png"]:
        (tmp_path / name).write_bytes(b"x")
    scenes = build_even_split_storyboard(tmp_path, 10.0)
    durations = [scene["duration"] for scene in scenes]
    assert durations == [3.333, 3.333, 3.334]
    assert abs(sum(durations) - 10.0) < 1e-6


def test_motion_rotation_cycles_and_repeats(tmp_path: Path) -> None:
    for index in range(7):
        (tmp_path / f"s{index}.png").write_bytes(b"x")
    scenes = build_even_split_storyboard(tmp_path, 70.0)
    motions = [scene["motion"] for scene in scenes]
    assert motions[: len(MOTION_CYCLE)] == list(MOTION_CYCLE)
    assert motions[len(MOTION_CYCLE)] == MOTION_CYCLE[0]
    assert motions[len(MOTION_CYCLE) + 1] == MOTION_CYCLE[1]


def test_ending_image_appends_static_outro(tmp_path: Path) -> None:
    for name in ["a1.png", "a2.png"]:
        (tmp_path / name).write_bytes(b"x")
    ending = tmp_path / "end.png"
    ending.write_bytes(b"x")
    scenes = build_even_split_storyboard(tmp_path, 20.0, ending_image=ending)
    # Two middle images split the full voice; the ending extends the video by OUTRO_SECONDS.
    assert len(scenes) == 3
    assert scenes[-1]["motion"] == "static"
    assert scenes[-1]["duration"] == OUTRO_SECONDS
    assert abs(sum(s["duration"] for s in scenes) - (20.0 + OUTRO_SECONDS)) < 1e-6


def test_intro_image_overlays_start_without_adding_time(tmp_path: Path) -> None:
    for name in ["a1.png", "a2.png"]:
        (tmp_path / name).write_bytes(b"x")
    intro = tmp_path / "thumb.png"
    intro.write_bytes(b"x")
    scenes = build_even_split_storyboard(tmp_path, 30.0, intro_image=intro)
    assert scenes[0]["motion"] == "static"
    assert scenes[0]["duration"] == INTRO_SECONDS
    # Total stays at the voice duration: intro eats into the split base.
    assert abs(sum(s["duration"] for s in scenes) - 30.0) < 1e-6


def test_intro_skipped_when_voice_too_short(tmp_path: Path, capsys) -> None:
    (tmp_path / "a1.png").write_bytes(b"x")
    intro = tmp_path / "thumb.png"
    intro.write_bytes(b"x")
    scenes = build_even_split_storyboard(tmp_path, INTRO_SECONDS - 1.0, intro_image=intro)
    assert all(s["motion"] != "static" for s in scenes)
    assert "too short" in capsys.readouterr().out


def test_interleave_spreads_clips_across_the_whole_order() -> None:
    images = [Path(f"img{i}.png") for i in range(10)]
    videos = [Path("v0.mp4"), Path("v1.mp4")]
    ordered = interleave_media_by_story_order(images, videos)
    kinds = [kind for kind, _path in ordered]
    # 12 media total, both clips present, and NOT bunched at the front.
    assert len(ordered) == 12
    assert kinds.count("video") == 2
    video_positions = [i for i, k in enumerate(kinds) if k == "video"]
    # First clip lands in the first half, second clip in the second half — spread, not adjacent.
    assert video_positions[0] < 6 <= video_positions[1]


def test_interleave_preserves_each_lists_order() -> None:
    images = [Path("a.png"), Path("b.png"), Path("c.png")]
    videos = [Path("v1.mp4"), Path("v2.mp4")]
    ordered = interleave_media_by_story_order(images, videos)
    assert [p.name for k, p in ordered if k == "image"] == ["a.png", "b.png", "c.png"]
    assert [p.name for k, p in ordered if k == "video"] == ["v1.mp4", "v2.mp4"]


def test_interleave_handles_empty_video_list() -> None:
    images = [Path("a.png"), Path("b.png")]
    ordered = interleave_media_by_story_order(images, [])
    assert [k for k, _ in ordered] == ["image", "image"]


def _write_job(job_path: Path) -> None:
    job_path.write_text(
        """
version: 1
project:
  title: autogen
inputs:
  voice: voice.wav
  media_dir: Image
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )


def test_auto_storyboard_writes_validated_scenes(tmp_path: Path) -> None:
    job_path = tmp_path / "job.yaml"
    _write_job(job_path)
    images_dir = tmp_path / "Image"
    images_dir.mkdir()
    for name in ["scene_001_4K.jpg", "scene_002_4K.jpg", "scene_010_4K.jpg"]:
        (images_dir / name).write_bytes(b"x")

    auto_storyboard(job_path, images_dir, voice_duration=12.0)

    data = yaml.safe_load(job_path.read_text(encoding="utf-8"))
    job = JobSpec.model_validate(data)
    assert len(job.storyboard) == 3
    assert abs(sum(scene.duration for scene in job.storyboard) - 12.0) < 1e-6
    # Natural order keeps _010 last; paths stay relative to the job dir.
    assert [scene.image for scene in job.storyboard] == [
        Path("Image/scene_001_4K.jpg"),
        Path("Image/scene_002_4K.jpg"),
        Path("Image/scene_010_4K.jpg"),
    ]
    # Existing keys are preserved through the rewrite.
    assert data["project"]["title"] == "autogen"


def test_auto_storyboard_overwrites_with_warning(tmp_path: Path, capsys) -> None:
    job_path = tmp_path / "job.yaml"
    _write_job(job_path)
    images_dir = tmp_path / "Image"
    images_dir.mkdir()
    for name in ["a.png", "b.png"]:
        (images_dir / name).write_bytes(b"x")
    auto_storyboard(job_path, images_dir, voice_duration=8.0)
    capsys.readouterr()
    # Second run replaces the 2-scene board with a 3-scene board and warns.
    (images_dir / "c.png").write_bytes(b"x")
    auto_storyboard(job_path, images_dir, voice_duration=9.0)
    output = capsys.readouterr().out
    assert "2" in output  # names the old scene count being replaced
    job = JobSpec.model_validate(yaml.safe_load(job_path.read_text(encoding="utf-8")))
    assert len(job.storyboard) == 3
