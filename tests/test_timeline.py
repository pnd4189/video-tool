from pathlib import Path

import pytest
from pydantic import ValidationError

from videotool.core.job_spec import JobSpec, load_job
from videotool.core.timeline import compile_timeline


def test_video_scene_resolves_to_clip_path(tmp_path: Path) -> None:
    # A scene with a video clip renders from the clip (not an image); image may be absent.
    job = JobSpec.model_validate(
        {
            "version": 1,
            "project": {"title": "vid"},
            "inputs": {"voice": "voice.wav", "media_dir": "media"},
            "outputs": [{"preset": "youtube-16x9"}],
            "storyboard": [
                {"scene": 1, "video": "Video/clip1.mp4", "duration": 8.0},
                {"scene": 2, "image": "media/a.png", "duration": 8.0},
            ],
            "assets": {"policy": "allow-missing-local"},
        }
    )
    timeline = compile_timeline(job, tmp_path / "job.yaml", duration=16.0)
    assert timeline.scenes[0].media_path.name == "clip1.mp4"
    assert timeline.scenes[1].media_path.name == "a.png"


def test_video_wins_when_scene_has_both(tmp_path: Path) -> None:
    job = JobSpec.model_validate(
        {
            "version": 1,
            "project": {"title": "both"},
            "inputs": {"voice": "voice.wav", "media_dir": "media"},
            "outputs": [{"preset": "youtube-16x9"}],
            "storyboard": [
                {"scene": 1, "image": "media/a.png", "video": "Video/clip1.mp4", "duration": 8.0},
            ],
            "assets": {"policy": "allow-missing-local"},
        }
    )
    timeline = compile_timeline(job, tmp_path / "job.yaml", duration=8.0)
    assert timeline.scenes[0].media_path.name == "clip1.mp4"


def test_scene_without_image_or_video_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JobSpec.model_validate(
            {
                "version": 1,
                "project": {"title": "bad"},
                "inputs": {"voice": "voice.wav", "media_dir": "media"},
                "outputs": [{"preset": "youtube-16x9"}],
                "storyboard": [{"scene": 1, "duration": 8.0}],
                "assets": {"policy": "allow-missing-local"},
            }
        )


def test_compile_timeline_has_outputs_without_ffmpeg_strings() -> None:
    path = Path("examples/jobs/basic-audio-first/job.yaml")
    timeline = compile_timeline(load_job(path), path, duration=3.0)
    assert [output.preset.name for output in timeline.outputs] == ["youtube-16x9", "shorts-9x16"]
    assert timeline.duration == 3.0


def test_voice_pad_seconds_covers_scenes_past_the_voice(tmp_path: Path) -> None:
    # Scenes total 12s but the voice is only 10s -> pad the voice by the 2s remainder.
    job = JobSpec.model_validate(
        {
            "version": 1,
            "project": {"title": "pad"},
            "inputs": {"voice": "voice.wav", "media_dir": "media"},
            "outputs": [{"preset": "youtube-16x9"}],
            "storyboard": [
                {"scene": 1, "image": "media/a.png", "duration": 4.0},
                {"scene": 2, "image": "media/b.png", "duration": 8.0},
            ],
            "assets": {"policy": "allow-missing-local"},
        }
    )
    timeline = compile_timeline(job, tmp_path / "job.yaml", duration=10.0)
    assert abs(timeline.voice_pad_seconds - 2.0) < 1e-6


def test_voice_pad_seconds_zero_when_scenes_match_voice(tmp_path: Path) -> None:
    job = JobSpec.model_validate(
        {
            "version": 1,
            "project": {"title": "nopad"},
            "inputs": {"voice": "voice.wav", "media_dir": "media"},
            "outputs": [{"preset": "youtube-16x9"}],
            "storyboard": [{"scene": 1, "image": "media/a.png", "duration": 10.0}],
            "assets": {"policy": "allow-missing-local"},
        }
    )
    timeline = compile_timeline(job, tmp_path / "job.yaml", duration=10.0)
    assert timeline.voice_pad_seconds == 0.0


def test_outro_cta_card_aligns_with_overlay_ending(tmp_path: Path) -> None:
    # Regression: an ending image must overlay the voice tail (not extend past it), so the
    # spliced outro CTA card starts exactly when the outro CTA voice does — no 10s desync and
    # no -shortest truncation of the card.
    intro_cta, narration, outro_cta = 8.784, 100.0, 14.736
    composed_voice = intro_cta + narration + outro_cta
    # Storyboard spans the narration: intro overlay (10s) + body + ending overlay (10s).
    job = JobSpec.model_validate(
        {
            "version": 1,
            "project": {"title": "cta"},
            "inputs": {"voice": "v.mp3", "media_dir": "m"},
            "outputs": [{"preset": "youtube-16x9"}],
            "storyboard": [
                {"scene": 1, "image": "intro.jpg", "duration": 10.0, "motion": "static"},
                {"scene": 2, "image": "a.jpg", "duration": narration - 20.0},
                {"scene": 3, "image": "end.jpg", "duration": 10.0, "motion": "static"},
            ],
            "assets": {"policy": "allow-missing-local"},
        }
    )
    timeline = compile_timeline(
        job, tmp_path / "job.yaml", duration=composed_voice,
        cta_intro_seconds=intro_cta, cta_outro_seconds=outro_cta,
        cta_intro_image=tmp_path / "ic.jpg", cta_outro_image=tmp_path / "oc.jpg",
    )
    scenes_total = sum(scene.duration for scene in timeline.scenes)
    outro_card_start = sum(scene.duration for scene in timeline.scenes[:-1])
    outro_voice_start = intro_cta + narration
    assert abs(outro_card_start - outro_voice_start) < 1e-6  # card flush with voice
    assert abs(scenes_total - composed_voice) < 1e-6  # no pad -> no -shortest cut
    assert timeline.voice_pad_seconds == 0.0
