from pathlib import Path

from videotool.ai.subtitles import validate_srt, write_srt
from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.package.manifest import write_package_manifest
from videotool.package.youtube import parse_integrated_lufs, validate_package


def test_validate_srt_fails_missing_file(tmp_path: Path) -> None:
    assert validate_srt(tmp_path / "missing.srt")


def test_manifest_records_checksum(tmp_path: Path) -> None:
    media = tmp_path / "video.mp4"
    media.write_bytes(b"abc")
    manifest = tmp_path / "package-manifest.json"
    write_package_manifest([media], tmp_path / "job.yaml", manifest)
    assert "sha256" in manifest.read_text(encoding="utf-8")


def test_valid_srt_for_package(tmp_path: Path) -> None:
    srt = tmp_path / "captions.srt"
    write_srt(TranscriptResult("vi", [TranscriptSegment(0, 1, "hello")]), srt)
    assert validate_srt(srt) == []


def test_empty_package_fails_expected_video() -> None:
    checks = validate_package(Path("/tmp/definitely-empty-videotool-package"), expected_videos=["youtube-16x9.mp4"], require_srt=False)
    assert any(check.name == "video_exists" and check.status == "fail" for check in checks)


def test_package_does_not_self_reference_generated_reports() -> None:
    # quality-report.json / package-manifest.json are written AFTER validation runs, so the
    # validator must not assert them (they would always fail at generation time).
    checks = validate_package(Path("/tmp/definitely-empty-videotool-package"), expected_videos=["youtube-16x9.mp4"], require_srt=False)
    names = {check.name for check in checks}
    assert "quality_report" not in names
    assert "package_manifest" not in names


def test_parse_integrated_lufs_takes_summary_not_startup() -> None:
    # ebur128 prints near-silent startup I: readings, then the true integrated value in Summary.
    stderr = (
        "[Parsed_ebur128_0 @ 0x1] t: 0.1 TARGET:-23 LUFS    M: -70.0 S:-120.0     I: -70.0 LUFS\n"
        "[Parsed_ebur128_0 @ 0x1] t: 1.2 TARGET:-23 LUFS    M: -18.0 S: -20.0     I: -25.0 LUFS\n"
        "[Parsed_ebur128_0 @ 0x1] Summary:\n"
        "  Integrated loudness:\n"
        "    I:         -14.3 LUFS\n"
        "    Threshold: -24.5 LUFS\n"
    )
    assert parse_integrated_lufs(stderr) == -14.3


def test_parse_integrated_lufs_returns_none_without_match() -> None:
    assert parse_integrated_lufs("no loudness data here") is None
