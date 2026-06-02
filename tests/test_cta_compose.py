from pathlib import Path

from videotool.core.job_spec import load_job
from videotool.core.timeline import compile_timeline
from videotool.render.cta_compose import (
    _build_concat_command,
    offset_chapters,
    shift_srt,
)


def test_concat_command_normalizes_and_concats() -> None:
    cmd = " ".join(_build_concat_command([Path("a.mp3"), Path("b.wav"), Path("c.mp3")], Path("out.flac")))
    assert cmd.count("-i ") == 3
    assert "aresample=48000" in cmd
    assert "concat=n=3:v=0:a=1[out]" in cmd
    assert "-c:a flac" in cmd


def test_shift_srt_offsets_all_timestamps_with_hour_rollover() -> None:
    srt = "1\n00:59:58,000 --> 00:59:59,500\nHello\n"
    shifted = shift_srt(srt, 3.0)  # pushes past the hour boundary
    assert "01:00:01,000 --> 01:00:02,500" in shifted
    assert "Hello" in shifted


def test_shift_srt_noop_when_zero() -> None:
    srt = "1\n00:00:01,000 --> 00:00:02,000\nX\n"
    assert shift_srt(srt, 0) == srt


def test_offset_chapters_prepends_intro_and_shifts() -> None:
    chapters = [(0.0, "Chương 1"), (600.0, "Chương 2")]
    result = offset_chapters(chapters, 9.0)
    assert result[0] == (0.0, "Giới thiệu")
    assert result[1] == (9.0, "Chương 1")
    assert result[2] == (609.0, "Chương 2")


def test_offset_chapters_noop_without_intro() -> None:
    chapters = [(0.0, "Chương 1")]
    assert offset_chapters(chapters, 0.0) == chapters


def _job(tmp_path: Path) -> Path:
    (tmp_path / "media").mkdir()
    (tmp_path / "voice.wav").write_bytes(b"fake")
    for i in (1, 2, 3):
        (tmp_path / "media" / f"scene-{i:03}.png").write_bytes(b"fake")
    (tmp_path / "thumb.png").write_bytes(b"fake")
    (tmp_path / "end.png").write_bytes(b"fake")
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        """
version: 1
project: {title: cta}
inputs: {voice: voice.wav, media_dir: media}
outputs: [{preset: youtube-16x9}]
storyboard:
  - {scene: 1, image: media/scene-001.png, duration: 30.0}
  - {scene: 2, image: media/scene-002.png, duration: 30.0}
  - {scene: 3, image: media/scene-003.png, duration: 30.0}
assets: {policy: allow-missing-local}
""",
        encoding="utf-8",
    )
    return job_path


def test_compile_timeline_brackets_scenes_with_cta_cards(tmp_path: Path) -> None:
    job_path = _job(tmp_path)
    composed = tmp_path / "voice-cta.flac"
    timeline = compile_timeline(
        load_job(job_path), job_path, duration=112.0,
        cta_voice_path=composed,
        cta_intro_seconds=9.0,
        cta_outro_seconds=13.0,
        cta_intro_image=tmp_path / "thumb.png",
        cta_outro_image=tmp_path / "end.png",
    )
    # 3 narration scenes + intro card + outro card, in order.
    assert len(timeline.scenes) == 5
    assert timeline.scenes[0].duration == 9.0
    assert timeline.scenes[0].media_path == (tmp_path / "thumb.png").resolve()
    assert timeline.scenes[-1].duration == 13.0
    assert timeline.scenes[-1].media_path == (tmp_path / "end.png").resolve()
    assert timeline.voice_path == composed.resolve()


def test_compile_timeline_cta_image_defaults_to_edge_scenes(tmp_path: Path) -> None:
    job_path = _job(tmp_path)
    timeline = compile_timeline(
        load_job(job_path), job_path, duration=100.0,
        cta_voice_path=tmp_path / "voice-cta.flac",
        cta_intro_seconds=5.0,
        cta_outro_seconds=0.0,
    )
    # Only intro card added (outro seconds 0); falls back to first narration image.
    assert len(timeline.scenes) == 4
    assert timeline.scenes[0].media_path == (tmp_path / "media" / "scene-001.png").resolve()
