"""videotool review: contact-sheet frame choice, ebur128 parsing, section loudness findings."""
import shutil
import subprocess
from pathlib import Path

import pytest

from videotool.package import review
from videotool.package.review import Shot, loudness_timeline, pick_shots, section_report

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def test_shots_cover_cards_chapters_and_subtitles_in_order() -> None:
    chapters = [(0.0, "Chương 916: Rút sông"), (300.0, "Chương 917: Ấn chứng")]
    cues = [(float(i), float(i) + 4.0, "câu") for i in range(0, 600, 5)]
    shots = pick_shots(duration=623.45, intro=8.76, outro=14.69, narration=600.0, chapters=chapters, cues=cues)
    labels = [s.label for s in shots]
    assert labels[0] == "CTA in" and labels[-1] == "CTA out"
    assert {"intro card", "ending card", "ch 916", "ch 917", "subtitle 1/4", "subtitle 2/4", "subtitle 3/4"} <= set(labels)
    assert [s.t for s in shots] == sorted(s.t for s in shots)
    assert next(s.t for s in shots if s.label == "ch 917") == pytest.approx(8.76 + 303.0)
    assert all(0 < s.t < 623.45 for s in shots)


def test_many_chapters_are_spread_to_fit_the_sheet() -> None:
    chapters = [(i * 100.0, f"Chương {900 + i}: x") for i in range(40)]
    shots = pick_shots(duration=4100.0, intro=0.0, outro=0.0, narration=4100.0, chapters=chapters, cues=[])
    chapter_labels = [s.label for s in shots if s.label.startswith("ch ")]
    assert len(shots) <= review.MAX_SHOTS
    assert chapter_labels[0] == "ch 900" and chapter_labels[-1] == "ch 939"


def _frames(spec: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    """(from, to, level) spans -> 100 ms frames with M = S = level."""
    out = []
    for lo, hi, level in spec:
        t = lo
        while t < hi:
            out.append((round(t, 1), level, level))
            t += 0.1
    return out


def test_section_report_flags_a_quiet_cta_and_a_loud_sfx() -> None:
    frames = _frames([(0, 9, -15.0), (9, 99, -15.0), (99, 101, -3.0), (101, 120, -15.0), (120, 135, -21.0)])
    summary = {"integrated_lufs": -14.1, "lra_lu": 4.0, "true_peak_dbtp": -0.9}
    sfx = [{"t": 99.0, "file": "boom.mp3", "length": 2.0, "added_lu": 9.0}]
    report, warnings = section_report(frames, summary, intro=9.0, narration=111.0, duration=135.0,
                                      outro=15.0, sfx=sfx)
    assert report["narration_lufs"] == -15.0 and report["cta_out_lufs"] == -21.0
    assert report["sfx"][0]["over_narration_lu"] == 12.0
    assert any("cta out" in w for w in warnings)
    assert any("boom.mp3" in w and "over the voice" in w for w in warnings)
    assert not any("integrated" in w or "true peak" in w for w in warnings)


def test_section_report_flags_a_faint_sfx_and_loudness_off_target() -> None:
    frames = _frames([(0, 60, -16.0)])
    summary = {"integrated_lufs": -17.0, "lra_lu": 3.0, "true_peak_dbtp": 0.2}
    sfx = [{"t": 30.0, "file": "wind.mp3", "length": 3.0, "added_lu": 0.2}]
    _, warnings = section_report(frames, summary, intro=0.0, narration=60.0, duration=60.0, outro=0.0, sfx=sfx)
    assert any("integrated loudness -17.0" in w for w in warnings)
    assert any("true peak 0.2" in w for w in warnings)
    assert any("wind.mp3" in w and "barely audible" in w for w in warnings)


@needs_ffmpeg
def test_sheet_and_loudness_from_a_real_clip(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=640x360:d=6",
                    "-f", "lavfi", "-i", "sine=f=440:d=6", "-shortest", "-c:v", "libx264", "-c:a", "aac",
                    str(clip)], check=True)
    sheet = review.contact_sheet(clip, [Shot(1.0, "a"), Shot(2.5, "b"), Shot(4.0, "ch 1"), Shot(5.5, "d"),
                                        Shot(5.8, "e")], tmp_path / "sheet.png")
    width, height = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of",
                                    "csv=p=0", str(sheet)], capture_output=True, text=True).stdout.strip().split(",")
    assert (int(width), int(height)) == (4 * review.TILE_W + 3 * 4, 2 * review.TILE_H + 4)
    frames, summary = loudness_timeline(clip)
    assert len(frames) > 40 and summary["integrated_lufs"] is not None
    assert summary["true_peak_dbtp"] is not None and summary["true_peak_dbtp"] < 0
