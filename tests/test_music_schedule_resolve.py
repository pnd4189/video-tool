from pathlib import Path

import pytest

from videotool.core.errors import ValidationError
from videotool.core.job_spec import MusicCueSpec
from videotool.core.services import _resolve_music_schedule, _resolve_track

_TRACKS = [Path("01-a.mp3"), Path("02-b.mp3"), Path("03-c.mp3")]


def test_resolve_track_by_index_and_name() -> None:
    assert _resolve_track(1, _TRACKS).name == "01-a.mp3"
    assert _resolve_track("02-b", _TRACKS).name == "02-b.mp3"
    assert _resolve_track("c", _TRACKS).name == "03-c.mp3"  # substring match


def test_resolve_track_out_of_range_and_missing() -> None:
    with pytest.raises(ValidationError):
        _resolve_track(9, _TRACKS)
    with pytest.raises(ValidationError):
        _resolve_track("zzz", _TRACKS)


def test_schedule_boundaries_use_starts_and_apply_intro_offset() -> None:
    # Cue starts (not ends) define segment boundaries; first fills from 0, last fills to target.
    # intro_offset=10 shifts narration-aligned starts onto the composed timeline.
    cues = [
        MusicCueSpec(track=1, start=0, end=300),
        MusicCueSpec(track=2, start=300, end=600),
        MusicCueSpec(track=3, start=600, end=900),
    ]
    segments = _resolve_music_schedule(cues, _TRACKS, intro_offset=10.0, target_duration=920.0)
    names_durations = [(p.name, round(sec, 1), gain) for p, sec, gain in segments]
    assert names_durations == [
        ("01-a.mp3", 310.0, None),  # 0 -> 310 (cue2.start 300 + offset 10)
        ("02-b.mp3", 300.0, None),  # 310 -> 610
        ("03-c.mp3", 310.0, None),  # 610 -> 920 (target)
    ]


def test_schedule_drops_segments_past_video_end() -> None:
    cues = [
        MusicCueSpec(track=1, start=0, end=100),
        MusicCueSpec(track=2, start=100, end=200),
    ]
    # target shorter than the second cue's start -> only the first segment survives.
    segments = _resolve_music_schedule(cues, _TRACKS, intro_offset=0.0, target_duration=80.0)
    assert [p.name for p, _, _ in segments] == ["01-a.mp3"]
    assert segments[0][1] == pytest.approx(80.0)
