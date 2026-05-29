from pathlib import Path

from videotool.core.job_spec import JobSpec, load_job
from videotool.core.timeline import compile_timeline


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
