from pathlib import Path

from videotool.core.job_spec import load_job
from videotool.core.timeline import compile_timeline


def test_compile_timeline_has_outputs_without_ffmpeg_strings() -> None:
    path = Path("examples/jobs/basic-audio-first/job.yaml")
    timeline = compile_timeline(load_job(path), path, duration=3.0)
    assert [output.preset.name for output in timeline.outputs] == ["youtube-16x9", "shorts-9x16"]
    assert timeline.duration == 3.0
