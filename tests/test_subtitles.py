from pathlib import Path

from videotool.ai.subtitles import format_srt_timestamp, validate_srt, write_srt
from videotool.ai.transcribe import TranscriptResult, TranscriptSegment


def test_srt_timestamp_format() -> None:
    assert format_srt_timestamp(65.432) == "00:01:05,432"


def test_write_srt_preserves_vietnamese(tmp_path: Path) -> None:
    output = tmp_path / "captions.srt"
    transcript = TranscriptResult("vi", [TranscriptSegment(0, 1.2, "Xin chào Việt Nam")])
    write_srt(transcript, output)
    assert "Việt Nam" in output.read_text(encoding="utf-8")
    assert validate_srt(output) == []
