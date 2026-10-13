from __future__ import annotations

from videotool.core.timeline import Timeline

SIDECHAIN_PARAMS = "threshold=0.05:ratio=8:attack=5:release=400:makeup=2"
# amix ends on the voice's EOF and drops the voice it still holds unmixed: 0.03-0.33 s of the outro
# CTA on the BT Chap 68-72 renders, 1.15 s re-running Chap 71's graph locally (2026-10-13), and
# `-shortest` then cut the video to match. Silence past the voice takes that loss instead; every
# render bounds its output by the video (`-shortest` / `-t`), so the guard never reaches the file.
MIX_TAIL_GUARD_SECONDS = 2.0


def audio_settings(timeline: Timeline) -> dict[str, object]:
    return {
        "voice_gain_db": timeline.voice_gain_db,
        "music_gain_db": timeline.music_gain_db,
        "duck": timeline.duck,
        "normalize_lufs": timeline.normalize_lufs,
        "voice_pad_seconds": timeline.voice_pad_seconds,
    }


def _loudnorm_suffix(normalize_lufs: float | None) -> str:
    # ":g" drops a trailing ".0" so -14.0 renders as the canonical loudnorm=I=-14.
    if normalize_lufs is None:
        return ""
    return f",loudnorm=I={normalize_lufs:g}:TP=-1:LRA=11"


def _voice_pad_suffix(voice_pad_seconds: float) -> str:
    # Append trailing silence so the voice spans the full video when scenes extend past the
    # narration (e.g. an ending image). Keeps `-shortest` from clipping the outro.
    if voice_pad_seconds < 0.001:
        return ""
    return f",apad=pad_dur={voice_pad_seconds:.3f}"


def build_audio_graph(
    voice_input: str,
    music_input: str | None,
    *,
    voice_gain_db: float,
    music_gain_db: float,
    duck: bool,
    normalize_lufs: float | None,
    voice_pad_seconds: float = 0.0,
) -> str:
    """Build the audio filtergraph shared by the single-background, storyboard, and
    segmented-mux paths.

    With music: returns a filter_complex chain consuming the voice/music inputs and
    ending in [aout]. Without music (``music_input is None``): returns the value for ``-af``.
    dB gains are emitted as ``volume={x}dB``; ducking and the final loudnorm pass are
    each independently toggleable. ``voice_pad_seconds`` appends trailing silence to the voice;
    a music mix appends ``MIX_TAIL_GUARD_SECONDS`` more.
    """
    norm = _loudnorm_suffix(normalize_lufs)
    if music_input is None:
        return f"volume={voice_gain_db}dB{_voice_pad_suffix(voice_pad_seconds)}{norm}"
    pad = _voice_pad_suffix(voice_pad_seconds + MIX_TAIL_GUARD_SECONDS)
    # Pin an explicit stereo layout on both feeds. FLAC intermediates (voice-cta / music
    # schedule) carry a channel count but no layout tag; older ffmpeg (4.4.x on the cloud box)
    # then refuses to negotiate formats for sidechaincompress/amix ("No channel layout for
    # input 1" -> Conversion failed). ffmpeg 6.x infers it, which is why local renders never hit
    # this. aformat labels the existing 2 channels without resampling.
    layout = ",aformat=channel_layouts=stereo"
    voice_vol = f"[{voice_input}]volume={voice_gain_db}dB{pad}{layout}"
    music_vol = f"[{music_input}]volume={music_gain_db}dB{layout}"
    if duck:
        # asplit duplicates the gained voice so the same stream both mixes and keys the duck.
        return (
            f"{voice_vol},asplit=2[voice][voicekey];"
            f"{music_vol}[musicpre];"
            f"[musicpre][voicekey]sidechaincompress={SIDECHAIN_PARAMS}[ducked];"
            f"[voice][ducked]amix=inputs=2:duration=first:normalize=0{norm}[aout]"
        )
    return (
        f"{voice_vol}[voice];"
        f"{music_vol}[musicpre];"
        f"[voice][musicpre]amix=inputs=2:duration=first:normalize=0{norm}[aout]"
    )


def build_audio_output_graph(
    voice_input: str,
    music_input: str | None,
    *,
    voice_gain_db: float,
    music_gain_db: float,
    duck: bool,
    normalize_lufs: float | None,
    voice_pad_seconds: float = 0.0,
) -> str:
    if music_input is not None:
        return build_audio_graph(
            voice_input,
            music_input,
            voice_gain_db=voice_gain_db,
            music_gain_db=music_gain_db,
            duck=duck,
            normalize_lufs=normalize_lufs,
            voice_pad_seconds=voice_pad_seconds,
        )
    audio_filter = build_audio_graph(
        voice_input,
        None,
        voice_gain_db=voice_gain_db,
        music_gain_db=music_gain_db,
        duck=duck,
        normalize_lufs=normalize_lufs,
        voice_pad_seconds=voice_pad_seconds,
    )
    return f"[{voice_input}]{audio_filter}[aout]"
