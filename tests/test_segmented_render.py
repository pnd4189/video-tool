from pathlib import Path
from types import SimpleNamespace

import pytest

from videotool.core import services
from videotool.core.job_spec import load_job
from videotool.core.timeline import compile_timeline
from videotool.render.executor import RenderExecutor
from videotool.render.profiles import get_profile
from videotool.render.segmented import build_segmented_render


def _scene_block(count: int) -> str:
    lines = []
    for index in range(1, count + 1):
        lines.append(f"  - scene: {index}")
        lines.append(f"    image: media/scene-{index:03}.png")
        lines.append("    duration: 2.0")
    return "\n".join(lines)


def _write_job(
    tmp_path: Path,
    scene_count: int,
    *,
    max_inline: int = 40,
    music: bool = True,
    enhance: str = "",
) -> Path:
    (tmp_path / "media").mkdir(exist_ok=True)
    (tmp_path / "voice.wav").write_bytes(b"fake")
    if music:
        (tmp_path / "music.mp3").write_bytes(b"fake")
    for index in range(1, scene_count + 1):
        (tmp_path / "media" / f"scene-{index:03}.png").write_bytes(b"fake")
    music_line = "  music: music.mp3\n" if music else ""
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        f"""
version: 1
project:
  title: segmented
inputs:
  voice: voice.wav
  media_dir: media
{music_line}outputs:
  - preset: youtube-16x9
render:
  max_inline_scenes: {max_inline}
{enhance}captions:
  mode: "off"
storyboard:
{_scene_block(scene_count)}
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    return job_path


def _timeline(job_path: Path, duration: float):
    return compile_timeline(load_job(job_path), job_path, duration=duration)


def test_segmented_plan_has_one_clip_per_scene_plus_mux(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 5)
    timeline = _timeline(job_path, 10.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    assert len(plan.scene_commands) == 5
    assert plan.mux_command[0] == "ffmpeg"
    # Mux step encodes audio at 256k (raised from 192k for listenability).
    assert "256k" in plan.mux_command
    assert "192k" not in plan.mux_command


def test_each_scene_clip_is_video_only_and_distinct(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 3)
    timeline = _timeline(job_path, 6.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    clip_names = [scene.output_path.name for scene in plan.scene_commands]
    assert clip_names == ["scene-0000.mp4", "scene-0001.mp4", "scene-0002.mp4"]
    for scene in plan.scene_commands:
        command = " ".join(scene.command)
        assert "-an" in scene.command  # video-only clip
        assert "-t 2.000" in command


def test_concat_text_lists_all_clips_in_order(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 4)
    timeline = _timeline(job_path, 8.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    lines = plan.concat_list_text.strip().splitlines()
    assert len(lines) == 4
    for scene, line in zip(plan.scene_commands, lines):
        assert line == f"file '{scene.output_path}'"


def test_mux_command_uses_concat_audio_graph_and_metadata(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 3)
    timeline = _timeline(job_path, 6.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    mux = " ".join(plan.mux_command)
    assert "-f concat" in mux
    assert "sidechaincompress" in mux  # voice-ducked music bed
    assert "loudnorm=I=-14:TP=-1:LRA=11" in mux
    assert "-metadata title=segmented" in mux
    assert "-c:v copy" in mux


def test_full_tier_segmented_mux_reencodes_with_overlay_graph(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 3, enhance="enhance:\n  tier: full\n  visualizer: false\n")
    timeline = _timeline(job_path, 6.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    mux = " ".join(plan.mux_command)
    assert "-c:v copy" not in mux
    assert "-filter_complex" in mux
    assert "-map [v]" in mux
    assert "dust.mp4" in mux
    assert "[2:a]volume=-30.0dB" in mux
    assert "[3:v]scale=1920:1080" in mux
    assert "subtitles=filename=" in mux
    assert "drawbox=" not in mux  # progress bar removed from all jobs
    assert "sidechaincompress" in mux


def test_full_tier_visualizer_preserves_padded_outro(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 2, enhance="enhance:\n  tier: full\n")
    timeline = _timeline(job_path, 2.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    mux = " ".join(plan.mux_command)
    assert "showwaves=" in mux
    assert "eof_action=pass" in mux
    assert "apad=pad_dur=2" in mux


def test_full_tier_segmented_without_music_keeps_particle_index(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 2, music=False, enhance="enhance:\n  tier: full\n  visualizer: false\n")
    timeline = _timeline(job_path, 4.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    mux = " ".join(plan.mux_command)
    assert "[2:v]scale=1920:1080" in mux
    assert "[1:a]volume=0.0dB" in mux
    assert "-map [aout]" in mux


def test_light_tier_particle_override_reencodes_segmented_mux(tmp_path: Path) -> None:
    job_path = _write_job(
        tmp_path,
        2,
        enhance=(
            "enhance:\n"
            "  tier: light\n"
            "  particles: true\n"
            "  subtitles: false\n"
            "  progress_bar: false\n"
            "  visualizer: false\n"
        ),
    )
    timeline = _timeline(job_path, 4.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    mux = " ".join(plan.mux_command)
    assert "-c:v copy" not in mux
    assert "[3:v]scale=1920:1080" in mux
    assert "subtitles=filename=" not in mux


def test_light_tier_subtitle_override_burns_segmented_subtitles(tmp_path: Path) -> None:
    job_path = _write_job(
        tmp_path,
        2,
        enhance=(
            "enhance:\n"
            "  tier: light\n"
            "  subtitles: true\n"
            "  particles: false\n"
            "  progress_bar: false\n"
            "  visualizer: false\n"
        ),
    )
    timeline = _timeline(job_path, 4.0)
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=tmp_path / "clips",
        concat_list_path=tmp_path / "concat.txt",
    )
    mux = " ".join(plan.mux_command)
    assert "-c:v copy" not in mux
    assert "subtitles=filename=" in mux
    assert "-map [v]" in mux


def test_routing_segmented_above_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job_path = _write_job(tmp_path, 6, max_inline=3)
    monkeypatch.setattr(services, "probe_media", lambda path: SimpleNamespace(duration=12.0))
    result = services.run_render(job_path, dry_run=True)
    assert len(result) == 1
    assert hasattr(result[0], "scene_commands")
    assert len(result[0].scene_commands) == 6


def test_routing_inline_at_or_below_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job_path = _write_job(tmp_path, 3, max_inline=3)
    monkeypatch.setattr(services, "probe_media", lambda path: SimpleNamespace(duration=6.0))
    result = services.run_render(job_path, dry_run=True)
    assert len(result) == 1
    assert not hasattr(result[0], "scene_commands")
    assert "xfade" in " ".join(result[0].command)


class _RecordingExecutor(RenderExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[list[str]] = []

    def _run(self, command: list[str], log_path: Path, preset: str) -> float:
        self.commands.append(command)
        # Simulate ffmpeg producing its output file (last arg) so the atomic .part rename works.
        Path(command[-1]).write_bytes(b"clip")
        return 0.0


class _CrashingExecutor(RenderExecutor):
    """Writes the .part output then raises, simulating a render killed mid-clip."""

    def __init__(self, crash_on_index: int) -> None:
        super().__init__()
        self.crash_on_index = crash_on_index
        self._calls = 0

    def _run(self, command: list[str], log_path: Path, preset: str) -> float:
        Path(command[-1]).write_bytes(b"partial")  # ffmpeg started writing the clip
        if self._calls == self.crash_on_index:
            raise RuntimeError("killed mid-clip")
        self._calls += 1
        return 0.0


def test_run_segmented_skips_existing_clips(tmp_path: Path) -> None:
    job_path = _write_job(tmp_path, 3)
    timeline = _timeline(job_path, 6.0)
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    plan = build_segmented_render(
        timeline,
        get_profile("libx264-fast"),
        timeline.outputs[0],
        clips_dir=clips_dir,
        concat_list_path=tmp_path / "concat.txt",
    )
    # Pre-render scene 1's clip: run_segmented must not re-encode it.
    plan.scene_commands[1].output_path.write_bytes(b"already-rendered")
    executor = _RecordingExecutor()
    executor.run_segmented(plan, tmp_path / "logs")
    ran = [" ".join(command) for command in executor.commands]
    assert not any("scene-0001" in command and "-an" in command for command in ran)
    assert any("scene-0000.part.mp4" in command for command in ran)
    assert any("-f concat" in command for command in ran)  # mux still runs
    assert (tmp_path / "concat.txt").exists()


def test_run_segmented_does_not_trust_interrupted_clip(tmp_path: Path) -> None:
    # A render killed mid-clip must leave NO final clip (only a .part), so a resumed run
    # re-encodes it instead of trusting a truncated file via size>0.
    job_path = _write_job(tmp_path, 3)
    timeline = _timeline(job_path, 6.0)
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    plan = build_segmented_render(
        timeline, get_profile("libx264-fast"), timeline.outputs[0],
        clips_dir=clips_dir, concat_list_path=tmp_path / "concat.txt",
    )
    with pytest.raises(RuntimeError):
        _CrashingExecutor(crash_on_index=1).run_segmented(plan, tmp_path / "logs")
    # Scene 0 finished (final exists); scene 1 was interrupted (only a .part, no final).
    assert plan.scene_commands[0].output_path.exists()
    interrupted = plan.scene_commands[1].output_path
    assert not interrupted.exists()
    assert interrupted.with_name(interrupted.stem + ".part" + interrupted.suffix).exists()

    # Resume: scene 1's stale .part is discarded and the clip is re-rendered cleanly.
    _RecordingExecutor().run_segmented(plan, tmp_path / "logs")
    assert interrupted.exists()
