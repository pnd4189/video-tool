import shutil
import subprocess
from pathlib import Path

import pytest

from videotool.ai.subtitles import validate_srt
from videotool.core.job_spec import load_job
from videotool.core.timeline import compile_timeline
from videotool.package.manifest import write_package_manifest
from videotool.package.youtube import write_description
from videotool.render.audio_graph import build_audio_graph
from videotool.render.commands import build_ffmpeg_command
from videotool.render.profiles import get_profile

MIX = {"voice_gain_db": 0.0, "music_gain_db": -30.0, "duck": True, "normalize_lufs": -14.0}


def test_audio_graph_uses_sidechain_and_lufs_target() -> None:
    path = Path("examples/jobs/basic-audio-first/job.yaml")
    timeline = compile_timeline(load_job(path), path, duration=3.0)
    plan = build_ffmpeg_command(timeline, get_profile("libx264-balanced"), timeline.outputs[0])
    joined = " ".join(plan.command)
    assert "sidechaincompress" in joined
    assert "loudnorm=I=-14:TP=-1:LRA=11" in joined


def test_music_mix_pads_the_voice_past_the_amix_tail_drop() -> None:
    assert "[1:a]volume=0.0dB,apad=pad_dur=2.000,aformat=" in build_audio_graph("1:a", "2:a", **MIX)
    assert "apad=pad_dur=5.000," in build_audio_graph("1:a", "2:a", **MIX, voice_pad_seconds=3.0)
    assert "apad" not in build_audio_graph("1:a", None, **MIX)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_music_mix_keeps_the_whole_voice(tmp_path: Path) -> None:
    # Stereo FLAC voice and music, as compose_voice and the music schedule write them: without the
    # guard this graph ended 1.1 s before the 30 s voice did.
    voice, music, mixed = tmp_path / "voice.flac", tmp_path / "music.flac", tmp_path / "mixed.flac"
    for path, tone, fmt in ((voice, "sine=f=220:d=30", "s32"), (music, "sine=f=330:d=30", "s16")):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"{tone}:sample_rate=48000",
                        "-ac", "2", "-sample_fmt", fmt, str(path)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(voice), "-stream_loop", "-1", "-i", str(music),
                    "-filter_complex", build_audio_graph("0:a", "1:a", **MIX), "-map", "[aout]", str(mixed)],
                   check=True)
    seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "csv=p=0", str(mixed)], capture_output=True, text=True).stdout)
    assert seconds >= 30.0


def test_video_metadata_is_embedded() -> None:
    path = Path("examples/jobs/basic-audio-first/job.yaml")
    timeline = compile_timeline(load_job(path), path, duration=3.0)
    plan = build_ffmpeg_command(timeline, get_profile("libx264-balanced"), timeline.outputs[0])
    assert "-metadata" in plan.command
    assert any(arg.startswith("title=") for arg in plan.command)


def test_vaapi_profiles_are_removed() -> None:
    with pytest.raises(ValueError, match="Unknown render profile"):
        get_profile("h264-vaapi-draft")


def test_description_with_chapters_and_tags(tmp_path: Path) -> None:
    license_report = tmp_path / "license-report.md"
    license_report.write_text("# License\n", encoding="utf-8")
    output = tmp_path / "description.txt"
    write_description(
        "My YouTube Video",
        license_report,
        output,
        description="Story about coding.",
        chapters=[(0.0, "Intro"), (65.0, "Main"), (3725.0, "Outro")],
        tags=["coding", "python"],
        cta="Subscribe for more!",
    )
    text = output.read_text(encoding="utf-8")
    assert "00:00 Intro" in text
    assert "01:05 Main" in text
    assert "01:02:05 Outro" in text
    assert "#coding" in text
    assert "Subscribe for more!" in text
    assert "license-report.md" in text


def test_srt_validate_handles_crlf(tmp_path: Path) -> None:
    srt = tmp_path / "win.srt"
    srt.write_bytes(
        b"1\r\n00:00:00,000 --> 00:00:01,000\r\nHello\r\n\r\n2\r\n00:00:01,000 --> 00:00:02,000\r\nWorld\r\n"
    )
    assert validate_srt(srt) == []


def test_manifest_does_not_include_itself(tmp_path: Path) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"abc")
    manifest_path = tmp_path / "package-manifest.json"
    write_package_manifest([media, manifest_path], tmp_path / "job.yaml", manifest_path)
    text = manifest_path.read_text(encoding="utf-8")
    assert "video.mp4" in text
    assert "package-manifest.json" not in text


def test_filter_escape_handles_brackets_and_semicolons() -> None:
    from videotool.render.overlay_graph import _escape_filter_value

    escaped = _escape_filter_value(Path("/tmp/foo[bar]/captions;subtitle.srt"))
    assert "[" not in escaped.replace("\\[", "")
    assert "]" not in escaped.replace("\\]", "")
    assert ";" not in escaped.replace("\\;", "")
