from pathlib import Path

import yaml

from videotool.cli import commands
from videotool.cli.storyboard_commands import link_parallax
from videotool.core.job_spec import JobSpec
from videotool.core.parallax_link import find_clip, link_parallax_clips


def _write_job(job_dir: Path, scenes: list[dict]) -> Path:
    data = {
        "version": 1,
        "project": {"title": "t", "language": "vi"},
        "inputs": {"voice": "voice.wav", "media_dir": "Image"},
        "outputs": [{"preset": "youtube-16x9"}],
        "storyboard": scenes,
        "captions": {"mode": "off"},
        "assets": {"policy": "allow-missing-local"},
        "render": {"encoder": "libx264-balanced"},
    }
    job = job_dir / "job.yaml"
    job.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return job


def _scenes(job: Path) -> list[dict]:
    return yaml.safe_load(job.read_text(encoding="utf-8"))["storyboard"]


def _img_scene(n: int, name: str) -> dict:
    return {"scene": n, "image": f"Image/{name}", "duration": 5.0,
            "motion": "slow-push", "transition": "crossfade"}


def _clip(clips_dir: Path, name: str) -> None:
    clips_dir.mkdir(parents=True, exist_ok=True)
    (clips_dir / name).write_bytes(b"x")


def test_image_scene_with_matching_clip_is_swapped(tmp_path: Path) -> None:
    job = _write_job(tmp_path, [_img_scene(1, "scene_001.jpg")])
    _clip(tmp_path / "Parallax", "scene_001.mp4")
    link_parallax(job, Path("Parallax"))
    scene = _scenes(job)[0]
    assert "image" not in scene
    assert scene["video"] == "Parallax/scene_001.mp4"
    assert scene["motion"] == "static"
    assert scene["duration"] == 5.0
    assert scene["transition"] == "crossfade"
    JobSpec.model_validate(yaml.safe_load(job.read_text(encoding="utf-8")))


def test_missing_clip_leaves_scene_unchanged(tmp_path: Path) -> None:
    job = _write_job(tmp_path, [_img_scene(1, "scene_002.jpg")])
    (tmp_path / "Parallax").mkdir()
    link_parallax(job, Path("Parallax"))
    scene = _scenes(job)[0]
    assert scene["image"] == "Image/scene_002.jpg"
    assert "video" not in scene


def test_existing_video_scene_untouched(tmp_path: Path) -> None:
    job = _write_job(tmp_path, [{"scene": 1, "video": "Video/broll.mp4", "duration": 4.0,
                                 "motion": "static", "transition": "cut"}])
    _clip(tmp_path / "Parallax", "broll.mp4")  # a same-stem clip exists but must be ignored
    before = job.read_text(encoding="utf-8")
    link_parallax(job, Path("Parallax"))
    assert job.read_text(encoding="utf-8") == before


def test_stem_match_rules(tmp_path: Path) -> None:
    job = _write_job(tmp_path, [_img_scene(1, "scene_003.jpg"), _img_scene(2, "foo.jpg")])
    _clip(tmp_path / "Parallax", "scene_003.MP4")   # uppercase ext must match
    _clip(tmp_path / "Parallax", "foobar.mp4")      # different stem must NOT match foo.jpg
    link_parallax(job, Path("Parallax"))
    scenes = _scenes(job)
    assert scenes[0]["video"] == "Parallax/scene_003.MP4"
    assert "image" in scenes[1] and "video" not in scenes[1]


def test_idempotent_rerun(tmp_path: Path) -> None:
    job = _write_job(tmp_path, [_img_scene(1, "scene_001.jpg")])
    _clip(tmp_path / "Parallax", "scene_001.mp4")
    link_parallax(job, Path("Parallax"))
    after_first = job.read_text(encoding="utf-8")
    counts = link_parallax(job, Path("Parallax"))
    assert counts["swapped"] == 0
    assert job.read_text(encoding="utf-8") == after_first


def test_emitted_path_is_relative_to_job_dir(tmp_path: Path) -> None:
    job = _write_job(tmp_path, [_img_scene(1, "scene_001.jpg")])
    _clip(tmp_path / "Parallax", "scene_001.mp4")
    link_parallax(job, Path("Parallax"))
    assert _scenes(job)[0]["video"] == "Parallax/scene_001.mp4"


def test_missing_clips_dir_returns_config_error(tmp_path: Path) -> None:
    job = _write_job(tmp_path, [_img_scene(1, "scene_001.jpg")])
    code = commands.parallax_link(job, Path("DoesNotExist"))
    assert code == commands.CONFIG_ERROR


def test_find_clip_and_core_counts(tmp_path: Path) -> None:
    clips = tmp_path / "Parallax"
    _clip(clips, "a.mp4")
    assert find_clip(clips, "a") == clips / "a.mp4"
    assert find_clip(clips, "missing") is None
    scenes = [_img_scene(1, "a.jpg"), _img_scene(2, "b.jpg")]
    new_scenes, counts = link_parallax_clips(scenes, clips, tmp_path)
    assert counts == {"swapped": 1, "missing": 1, "skipped": 0}
    assert new_scenes[0]["video"] == "Parallax/a.mp4"
