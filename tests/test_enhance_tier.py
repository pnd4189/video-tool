from pathlib import Path

from videotool.core.job_spec import EnhanceSpec, load_job
from videotool.core.timeline import compile_timeline
from videotool.render.commands import build_ffmpeg_command
from videotool.render.profiles import get_profile
from videotool.render.segmented import build_segmented_render


def _scene_block(count: int) -> str:
    lines = []
    for index in range(1, count + 1):
        lines.append(f"  - scene: {index}")
        lines.append(f"    image: media/scene-{index:03}.png")
        lines.append("    duration: 2.0")
    return "\n".join(lines)


def _write_job(tmp_path: Path, scene_count: int, *, enhance: str = "") -> Path:
    (tmp_path / "media").mkdir(exist_ok=True)
    (tmp_path / "voice.wav").write_bytes(b"fake")
    (tmp_path / "music.mp3").write_bytes(b"fake")
    for index in range(1, scene_count + 1):
        (tmp_path / "media" / f"scene-{index:03}.png").write_bytes(b"fake")
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        f"""
version: 1
project:
  title: enhance
inputs:
  voice: voice.wav
  media_dir: media
  music: music.mp3
outputs:
  - preset: youtube-16x9
{enhance}storyboard:
{_scene_block(scene_count)}
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    return job_path


def _timeline(job_path: Path, duration: float):
    return compile_timeline(load_job(job_path), job_path, duration=duration)


# --- EnhanceSpec resolver ---------------------------------------------------


def test_default_tier_is_light_and_features_off() -> None:
    spec = EnhanceSpec()
    assert spec.tier == "light"
    assert not spec.is_on("subtitles")
    assert not spec.is_on("particles")
    assert not spec.is_on("progress_bar")
    assert not spec.is_on("visualizer")


def test_full_tier_turns_every_feature_on() -> None:
    spec = EnhanceSpec(tier="full")
    assert all(spec.is_on(name) for name in ("subtitles", "particles", "progress_bar", "visualizer"))


def test_per_feature_override_wins_over_tier() -> None:
    # Override can force a feature off under full, or on under light.
    assert EnhanceSpec(tier="full", subtitles=False).is_on("subtitles") is False
    assert EnhanceSpec(tier="light", particles=True).is_on("particles") is True


# --- tier-light lock: byte-identical render output ---------------------------


def test_tier_light_segmented_mux_still_copies_video(tmp_path: Path) -> None:
    # >40 scenes routes through the segmented path. Light tier must keep -c:v copy
    # (no overlay re-encode) and never inject subtitles into the mux.
    job_path = _write_job(tmp_path, 41)
    timeline = _timeline(job_path, 82.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-balanced"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    mux = " ".join(plan.mux_command)
    assert "-c:v copy" in mux
    assert "subtitles=" not in mux
    # Video is mapped straight from the concat stream, not from a filter_complex label.
    assert "-map 0:v:0" in mux


def test_tier_light_inline_command_has_no_overlays(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 3)
    timeline = _timeline(job_path, 6.0)
    plan = build_ffmpeg_command(timeline, get_profile("libx264-balanced"), timeline.outputs[0])
    command = " ".join(plan.command)
    assert "subtitles=" not in command
    assert "showwaves" not in command


def test_tier_light_default_threads_into_timeline(tmp_path: Path) -> None:
    timeline = _timeline(_write_job(tmp_path, 3), 6.0)
    assert timeline.enhance_tier == "light"
    assert not timeline.enhance_subtitles
    assert not timeline.enhance_particles
    assert not timeline.enhance_progress_bar
    assert not timeline.enhance_visualizer


def test_full_tier_flags_resolve_onto_timeline(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 3, enhance="enhance:\n  tier: full\n")
    timeline = _timeline(job_path, 6.0)
    assert timeline.enhance_tier == "full"
    assert timeline.enhance_subtitles
    assert timeline.enhance_visualizer
