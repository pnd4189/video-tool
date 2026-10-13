"""render.bake_overlays: subtitles / mood / waveform drawn inside the scene clips, mux = stream copy."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from videotool.core import services
from videotool.core.job_spec import load_job
from videotool.core.timeline import compile_timeline
from videotool.render import segmented as segmented_module
from videotool.render.profiles import PROFILES, get_profile
from videotool.render.segmented import build_segmented_render

AUDIO_STORY = "enhance:\n  tier: light\n  subtitles: true\n  visualizer: true\n  subtitle_color: yellow\n"


def _job(tmp_path: Path, durations: list[float], *, enhance: str = AUDIO_STORY, render: str = "",
         extra_inputs: str = "") -> Path:
    (tmp_path / "media").mkdir(exist_ok=True)
    (tmp_path / "voice.wav").write_bytes(b"fake")
    (tmp_path / "music.mp3").write_bytes(b"fake")
    scenes = []
    for index, duration in enumerate(durations, start=1):
        (tmp_path / "media" / f"scene-{index:03}.png").write_bytes(b"fake")
        scenes.append(f"  - scene: {index}\n    image: media/scene-{index:03}.png\n    duration: {duration}")
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        "version: 1\nproject:\n  title: baked\ninputs:\n  voice: voice.wav\n  media_dir: media\n"
        f"  music: music.mp3\n{extra_inputs}outputs:\n  - preset: youtube-16x9\n"
        f"render:\n  max_inline_scenes: 1\n{render}{enhance}captions:\n  mode: \"off\"\n"
        "storyboard:\n" + "\n".join(scenes) + "\nassets:\n  policy: allow-missing-local\n",
        encoding="utf-8",
    )
    return job_path


def _plan(tmp_path: Path, job_path: Path, *, bake: bool):
    timeline = compile_timeline(load_job(job_path), job_path, duration=10.0)
    return build_segmented_render(
        timeline, get_profile("libx264-faster-capped-2500k"), timeline.outputs[0],
        clips_dir=tmp_path / "clips", concat_list_path=tmp_path / "concat.txt", bake_overlays=bake,
    )


def _arg(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def test_bake_off_keeps_overlays_in_the_mux(tmp_path: Path) -> None:
    job_path = _job(tmp_path, [2.0, 3.0])
    default = _plan(tmp_path, job_path, bake=False)
    for scene in default.scene_commands:
        assert "-frames:v" not in scene.command
        assert "subtitles=" not in " ".join(scene.command)
    mux = " ".join(default.mux_command)
    assert "subtitles=filename=" in mux and "showwaves" in mux and "-c:v copy" not in mux


def test_baked_clips_take_exact_frames_from_the_rounded_timeline(tmp_path: Path) -> None:
    # Cumulative ends 2.0, 3.01, 6.343, 6.943 s -> frames 60, 90, 190, 208 at 30 fps.
    job_path = _job(tmp_path, [2.0, 1.01, 3.333, 0.6])
    plan = _plan(tmp_path, job_path, bake=True)
    frames = [int(_arg(scene.command, "-frames:v")) for scene in plan.scene_commands]
    assert frames == [60, 30, 100, 18]
    starts = [_arg(scene.command, "-ss") for scene in plan.scene_commands]  # the voice slice per clip
    assert starts == ["0.000000", "2.000000", "3.000000", "6.333333"]
    assert plan.scenes_total_duration == pytest.approx(208 / 30)
    assert plan.reconcile is None


def test_baked_clip_draws_the_mux_chain_on_timeline_time(tmp_path: Path) -> None:
    job_path = _job(tmp_path, [2.0, 3.0])
    command = _plan(tmp_path, job_path, bake=True).scene_commands[1].command
    graph = _arg(command, "-filter_complex")
    voice_index = command.count("-i") - 1
    assert _arg(command, "-i") != str(tmp_path / "voice.wav")  # input 0 stays the scene still
    assert command[command.index("-ss"):command.index("-ss") + 6] == [
        "-ss", "2.000000", "-t", f"{91 / 30:.6f}", "-i", str((tmp_path / "voice.wav").resolve())]
    assert "[vclip]setpts=PTS+floor(2.000000/TB+0.5)[vtimeline]" in graph
    assert f"[{voice_index}:a]asetpts=PTS+floor(2.000000/TB+0.5)[vtimeline_voice]" in graph
    assert graph.index("subtitles=filename=") < graph.index("showwaves")
    assert "PrimaryColour=&H0000FFFF" in graph  # yellow subtitles survive the move
    assert graph.endswith("[vtimeline_out]setpts=PTS-STARTPTS[v]")


def test_baked_mux_is_a_stream_copy(tmp_path: Path) -> None:
    job_path = _job(tmp_path, [2.0, 3.0])
    mux = " ".join(_plan(tmp_path, job_path, bake=True).mux_command)
    assert "-c:v copy" in mux
    assert "subtitles=" not in mux and "showwaves" not in mux
    assert "loudnorm" in mux  # the audio graph is unchanged


def test_baked_mux_cuts_at_the_clip_total(tmp_path: Path) -> None:
    job_path = _job(tmp_path, [2.0, 1.01, 3.333, 0.6])
    baked, regular = _plan(tmp_path, job_path, bake=True), _plan(tmp_path, job_path, bake=False)
    assert _arg(baked.mux_command, "-t") == f"{208 / 30:.6f}"
    assert "-shortest" not in baked.mux_command
    assert "-shortest" in regular.mux_command


def test_atmosphere_is_blended_before_the_baked_overlays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(segmented_module, "probe_media", lambda path: SimpleNamespace(duration=18.0))
    (tmp_path / "fireflies.mp4").write_bytes(b"fake")
    job_path = _job(tmp_path, [2.0, 3.0], enhance=AUDIO_STORY + "  atmosphere: true\n",
                    extra_inputs="  particle_overlay: fireflies.mp4\n")
    plan = _plan(tmp_path, job_path, bake=True)
    graph = _arg(plan.scene_commands[1].command, "-filter_complex")
    assert graph.index("blend=all_mode=screen") < graph.index("setpts=PTS+floor(")
    assert _arg(plan.scene_commands[1].command, "-ss") == "2.000"  # the overlay loop seek
    assert "fireflies.mp4" not in " ".join(plan.mux_command)


def test_nothing_to_bake_keeps_the_regular_plan(tmp_path: Path) -> None:
    job_path = _job(tmp_path, [2.0, 3.0], enhance="enhance:\n  tier: light\n")
    baked, regular = _plan(tmp_path, job_path, bake=True), _plan(tmp_path, job_path, bake=False)
    assert [s.command for s in baked.scene_commands] == [s.command for s in regular.scene_commands]
    assert baked.mux_command == regular.mux_command


def test_particles_stay_in_the_mux(tmp_path: Path) -> None:
    job_path = _job(tmp_path, [2.0, 3.0], enhance=AUDIO_STORY + "  particles: true\n")
    baked, regular = _plan(tmp_path, job_path, bake=True), _plan(tmp_path, job_path, bake=False)
    assert [s.command for s in baked.scene_commands] == [s.command for s in regular.scene_commands]
    assert baked.mux_command == regular.mux_command


def test_job_flag_defaults_off_and_reaches_the_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "probe_media", lambda path: SimpleNamespace(duration=5.0))
    off = _job(tmp_path, [2.0, 3.0])
    assert load_job(off).render.bake_overlays is False
    on = _job(tmp_path, [2.0, 3.0], render="  bake_overlays: true\n  encoder: libx264-faster-capped-2500k\n")
    plan = services.build_segmented_plans(on, workspace_root=tmp_path / "ws")[0]
    assert all("-frames:v" in scene.command for scene in plan.scene_commands)
    assert "-preset faster" in " ".join(plan.scene_commands[0].command)


def test_faster_profiles_keep_the_vbv_caps() -> None:
    for cap, maxrate in (("", "2800k"), ("-2500k", "2500k"), ("-2200k", "2200k")):
        profile = PROFILES[f"libx264-faster-capped{cap}"]
        assert (profile.encoder, profile.preset, profile.crf) == ("libx264", "faster", 20)
        assert profile.extra_args[:2] == ("-maxrate", maxrate)
