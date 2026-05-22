from pathlib import Path

from videotool.ai.subtitles import validate_srt, write_srt
from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.package.manifest import write_package_manifest
from videotool.package.youtube import validate_package


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
