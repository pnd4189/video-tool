from pathlib import Path

from videotool.core.timeline import Timeline, TimelineOutput
from videotool.render.overlay_graph import (
    build_scene_atmosphere,
    build_video_overlay,
    caption_filter,
    particle_input_args,
)
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
        "enhance_visualizer": True,
    }
    values.update(overrides)
    return Timeline(**values)


def test_full_overlay_graph_layers_in_order() -> None:
    graph = build_video_overlay("vbase", "v", _timeline(), _output(), particle_input_idx=3, audio_label="voiceviz")

    # Progress bar removed; order is now subtitles -> particles -> visualizer.
    assert graph.index("subtitles=") < graph.index("overlay=shortest=1") < graph.index("showwaves=")
    assert "drawbox=" not in graph
    assert "eof_action=pass" in graph
    assert "[v]" in graph


def test_group_a_effects_apply_when_enabled() -> None:
    graph = build_video_overlay(
        "vbase", "v",
        _timeline(
            enhance_subtitles=False, enhance_particles=False, enhance_visualizer=False,
            enhance_vignette=True, enhance_grain=True, enhance_glow=True,
            enhance_flicker=True, enhance_color_grade="warm",
        ),
        _output(), particle_input_idx=None, audio_label=None,
    )
    assert "colorbalance=" in graph and "vignette=" in graph
    assert "noise=" in graph and "blend=all_mode=screen" in graph and "sin(2*PI*t" in graph


def test_atmosphere_blends_overlay_clip_screen() -> None:
    graph = build_video_overlay(
        "vbase", "v",
        _timeline(
            enhance_subtitles=False, enhance_particles=False, enhance_visualizer=False,
            enhance_atmosphere=True,
        ),
        _output(), particle_input_idx=3, audio_label=None,
    )
    assert "[3:v]scale=" in graph and "blend=all_mode=screen:shortest=1" in graph


def test_overlay_graph_passthrough_when_layers_off() -> None:
    graph = build_video_overlay(
        "vbase",
        "v",
        _timeline(
            caption_mode="off",
            enhance_subtitles=False,
            enhance_particles=False,
            enhance_visualizer=False,
        ),
        _output(),
        particle_input_idx=None,
        audio_label=None,
    )

    assert graph == "[vbase]format=yuv420p[v]"


def test_caption_filter_default_white_has_no_colour_keys() -> None:
    # Default subtitle_color keeps libass defaults so existing output stays byte-identical.
    graph = caption_filter(_timeline(), _output())
    assert "subtitles=" in graph
    assert "PrimaryColour" not in graph and "OutlineColour" not in graph


def test_caption_filter_yellow_sets_ass_colours() -> None:
    graph = caption_filter(_timeline(enhance_subtitle_color="yellow"), _output())
    assert "PrimaryColour=&H0000FFFF" in graph
    assert "OutlineColour=&H00000000" in graph


def test_particle_input_uses_bundled_default() -> None:
    args = particle_input_args(_timeline(), _output())

    assert args[:3] == ["-stream_loop", "-1", "-i"]
    assert args[-1].endswith("dust.mp4")


def test_particle_input_honors_job_override() -> None:
    args = particle_input_args(_timeline(particle_overlay_path=Path("custom/snow.mp4")), _output())

    assert args == ["-stream_loop", "-1", "-i", "custom/snow.mp4"]


def test_atmosphere_can_be_excluded_from_the_graph() -> None:
    # The segmented path bakes the blend into each scene clip, so the mux must not repeat it.
    graph = build_video_overlay(
        "vbase", "v",
        _timeline(
            enhance_particles=False, enhance_visualizer=False, enhance_atmosphere=True,
        ),
        _output(), particle_input_idx=3, audio_label=None, include_atmosphere=False,
    )
    assert "blend=all_mode=screen" not in graph
    assert "subtitles=" in graph  # the rest of the graph is untouched


def test_scene_atmosphere_graph_blends_one_clip() -> None:
    graph = build_scene_atmosphere("vfade", "v", _output(), 1)
    assert "[1:v]scale=1920:1080" in graph
    assert "blend=all_mode=screen:shortest=1" in graph
    assert graph.endswith("[v]")
