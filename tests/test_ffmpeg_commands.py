from pathlib import Path

from videotool.core.job_spec import load_job
from videotool.core.timeline import compile_timeline
from videotool.render.commands import build_ffmpeg_command
from videotool.render.profiles import get_profile


def test_ffmpeg_command_uses_argument_list() -> None:
    path = Path("examples/jobs/basic-audio-first/job.yaml")
    timeline = compile_timeline(load_job(path), path, duration=3.0)
    plan = build_ffmpeg_command(timeline, get_profile("libx264-balanced"), timeline.outputs[0])
    assert plan.command[0] == "ffmpeg"
    assert "-c:v" in plan.command
    assert plan.output_path.name == "youtube-16x9.mp4"


def test_static_motion_letterboxes_and_pads_voice_for_outro(tmp_path: Path) -> None:
    job_path = tmp_path / "job.yaml"
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "scene-001.png").write_bytes(b"fake")
    (tmp_path / "media" / "end.png").write_bytes(b"fake")
    job_path.write_text(
        """
version: 1
project:
  title: static-outro
inputs:
  voice: voice.wav
  media_dir: media
outputs:
  - preset: youtube-16x9
storyboard:
  - scene: 1
    image: media/scene-001.png
    duration: 10.0
    motion: slow-push
  - scene: 2
    image: media/end.png
    duration: 10.0
    motion: static
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    # Voice is 10s but scenes total 20s -> outro extends the video, voice must pad +10s.
    timeline = compile_timeline(load_job(job_path), job_path, duration=10.0)
    command = " ".join(build_ffmpeg_command(timeline, get_profile("libx264-fast"), timeline.outputs[0]).command)
    # Static scene letterboxes (pad) rather than cropping, and carries no zoompan of its own.
    assert "pad=1920:1080" in command
    assert "apad=pad_dur=10" in command


def test_storyboard_ffmpeg_command_uses_zoompan_and_xfade(tmp_path: Path) -> None:
    job_path = tmp_path / "job.yaml"
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "scene-001.png").write_bytes(b"fake")
    (tmp_path / "media" / "scene-002.png").write_bytes(b"fake")
    job_path.write_text(
        """
version: 1
project:
  title: storyboard
inputs:
  voice: voice.wav
  media_dir: media
outputs:
  - preset: youtube-16x9
storyboard:
  - scene: 1
    image: media/scene-001.png
    duration: 2.0
    motion: zoom-in
    transition: crossfade
  - scene: 2
    image: media/scene-002.png
    duration: 2.0
    motion: pan-right
    transition: fade
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    timeline = compile_timeline(load_job(job_path), job_path, duration=4.0)
    plan = build_ffmpeg_command(timeline, get_profile("libx264-fast"), timeline.outputs[0])
    command = " ".join(plan.command)
    assert "zoompan" in command
    assert "xfade" in command
    assert "media/scene-001.png" in command


def test_burn_subtitle_filter_is_added(tmp_path: Path) -> None:
    job_path = tmp_path / "job.yaml"
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "scene-001.png").write_bytes(b"fake")
    job_path.write_text(
        """
version: 1
project:
  title: captioned
inputs:
  voice: voice.wav
  media_dir: media
outputs:
  - preset: youtube-16x9
storyboard:
  - scene: 1
    image: media/scene-001.png
    duration: 2.0
captions:
  mode: srt-and-burn
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    timeline = compile_timeline(load_job(job_path), job_path, duration=2.0)
    plan = build_ffmpeg_command(timeline, get_profile("libx264-fast"), timeline.outputs[0])
    assert "subtitles=filename=" in " ".join(plan.command)
