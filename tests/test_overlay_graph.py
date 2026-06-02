from pathlib import Path

from videotool.core.timeline import Timeline, TimelineOutput
from videotool.render.overlay_graph import build_video_overlay, particle_input_args
from videotool.core.presets import get_preset


def _output() -> TimelineOutput:
    return TimelineOutput(
        preset=get_preset("youtube-16x9"),
        output_path=Path("outputs/youtube-16x9.mp4"),
    )


def _timeline(**overrides: object) -> Timeline:
    values = {
        "title": "overlay",
        "root": Path("."),
        "voice_path": Path("voice.wav"),
        "media_dir": Path("media"),
        "music_path": None,
        "caption_mode": "srt-and-burn",
        "subtitle_path": Path("outputs/captions.srt"),
        "particle_overlay_path": None,
        "scenes": [],
        "outputs": [_output()],
        "duration": 60.0,
        "enhance_tier": "full",
        "enhance_subtitles": True,
        "enhance_particles": True,
        "enhance_progress_bar": True,
        "enhance_visualizer": True,
    }
    values.update(overrides)
    return Timeline(**values)


def test_full_overlay_graph_layers_in_order() -> None:
    graph = build_video_overlay("vbase", "v", _timeline(), _output(), particle_input_idx=3, audio_label="voiceviz")

    assert graph.index("subtitles=") < graph.index("overlay=shortest=1") < graph.index("drawbox=")
    assert graph.index("drawbox=") < graph.index("showwaves=")
    assert "eof_action=pass" in graph
    assert "[v]" in graph


def test_overlay_graph_passthrough_when_layers_off() -> None:
    graph = build_video_overlay(
        "vbase",
        "v",
        _timeline(
            caption_mode="off",
            enhance_subtitles=False,
            enhance_particles=False,
            enhance_progress_bar=False,
            enhance_visualizer=False,
        ),
        _output(),
        particle_input_idx=None,
        audio_label=None,
    )

    assert graph == "[vbase]format=yuv420p[v]"


def test_particle_input_uses_bundled_default() -> None:
    args = particle_input_args(_timeline(), _output())

    assert args[:3] == ["-stream_loop", "-1", "-i"]
    assert args[-1].endswith("dust.mp4")


def test_particle_input_honors_job_override() -> None:
    args = particle_input_args(_timeline(particle_overlay_path=Path("custom/snow.mp4")), _output())

    assert args == ["-stream_loop", "-1", "-i", "custom/snow.mp4"]
