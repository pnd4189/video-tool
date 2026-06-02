import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from videotool.ai.subtitles import validate_srt
from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.cli.main import app
from videotool.core import services
from videotool.core.errors import DependencyError

runner = CliRunner()


def _make_job(tmp_path: Path) -> Path:
    (tmp_path / "media").mkdir()
    (tmp_path / "voice.wav").write_bytes(b"fake")
    (tmp_path / "media" / "scene-001.png").write_bytes(b"fake")
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        """
version: 1
project:
  title: transcribe
  language: vi
inputs:
  voice: voice.wav
  media_dir: media
outputs:
  - preset: youtube-16x9
storyboard:
  - scene: 1
    image: media/scene-001.png
    duration: 2.0
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    return job_path


class _StubTranscriber:
    """Stand-in for FasterWhisperTranscriber so tests never download or import whisper.
    Returns two fixed whisper spans; only their timing matters (text is discarded when a
    script aligns over it)."""

    def __init__(self, *, model_path: Path, **_: object) -> None:
        self.model_path = model_path

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptResult:
        return TranscriptResult(
            language=language or "vi",
            segments=[
                TranscriptSegment(0.0, 1.0, "raw whisper one"),
                TranscriptSegment(1.0, 2.0, "raw whisper two"),
            ],
        )


def test_transcribe_writes_srt_with_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "FasterWhisperTranscriber", _StubTranscriber)
    job_path = _make_job(tmp_path)
    result = runner.invoke(app, ["transcribe", str(job_path), "--model", "base"])
    assert result.exit_code == 0
    srt = tmp_path / "outputs" / "captions.srt"
    assert srt.exists()
    assert "raw whisper one" in srt.read_text(encoding="utf-8")


def test_transcribe_applies_script_alignment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "FasterWhisperTranscriber", _StubTranscriber)
    job_path = _make_job(tmp_path)
    script = tmp_path / "polished.txt"
    script.write_text("Polished line one. Polished line two.\n", encoding="utf-8")
    result = runner.invoke(app, ["transcribe", str(job_path), "--model", "base", "--script", str(script)])
    assert result.exit_code == 0
    srt = tmp_path / "outputs" / "captions.srt"
    text = srt.read_text(encoding="utf-8")
    # Whisper timing kept, spoken text replaced by the polished script wording.
    assert "Polished line one." in text
    assert "Polished line two." in text
    assert "raw whisper one" not in text
    assert validate_srt(srt) == []
    assert text.count(" --> ") == 2


def test_transcribe_missing_extra_shows_friendly_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Missing(_StubTranscriber):
        def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptResult:
            raise DependencyError("Install AI extras first: pip install -e '.[ai]'")

    monkeypatch.setattr(services, "FasterWhisperTranscriber", _Missing)
    job_path = _make_job(tmp_path)
    result = runner.invoke(app, ["transcribe", str(job_path), "--model", "base"])
    # commands.transcribe maps DependencyError -> dedicated exit code 3, message printed.
    # (Rich consumes "[ai]" as markup, so assert on the stable prose instead.)
    assert result.exit_code == 3
    assert "Install AI extras" in result.output


class _LongSpanTranscriber(_StubTranscriber):
    """One 30-minute speech span so aligned chapter headings land far enough apart to
    satisfy the >=10s YouTube gap rule."""

    def transcribe(self, audio_path: Path, language: str | None = None) -> TranscriptResult:
        return TranscriptResult(language=language or "vi", segments=[TranscriptSegment(0.0, 1800.0, "raw")])


def test_transcribe_emits_chapters_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    monkeypatch.setattr(services, "FasterWhisperTranscriber", _LongSpanTranscriber)
    job_path = _make_job(tmp_path)
    script = tmp_path / "story_vi.txt"
    script.write_text(
        "Chương 1: Khởi đầu\n\nMột đoạn văn dài mở màn cho chương đầu tiên của tập.\n\n"
        "Chương 2: Biến cố\n\nĐoạn văn của chương hai với nhiều tình tiết hơn hẳn.\n\n"
        "Chương 3: Kết thúc\n\nĐoạn văn khép lại chương ba và toàn bộ tập truyện này.\n",
        encoding="utf-8",
    )
    services.run_transcribe(job_path, model="base", script=script)
    chapters_path = tmp_path / "outputs" / "chapters.json"
    assert chapters_path.exists()
    chapters = json.loads(chapters_path.read_text(encoding="utf-8"))
    assert [c["title"] for c in chapters] == ["Chương 1: Khởi đầu", "Chương 2: Biến cố", "Chương 3: Kết thúc"]
    assert chapters[0]["start"] == 0.0
    assert chapters[1]["start"] >= 10.0


def test_transcribe_skips_chapters_when_no_headings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "FasterWhisperTranscriber", _LongSpanTranscriber)
    job_path = _make_job(tmp_path)
    script = tmp_path / "plain_vi.txt"
    script.write_text("Một đoạn văn. Hai đoạn văn. Ba đoạn văn.\n", encoding="utf-8")
    services.run_transcribe(job_path, model="base", script=script)
    assert not (tmp_path / "outputs" / "chapters.json").exists()


def test_importing_videotool_does_not_pull_faster_whisper() -> None:
    # tier-light installs must load the package without the optional extra; the adapter
    # imports faster_whisper only inside transcribe(), never at module import time.
    import videotool  # noqa: F401
    import videotool.core.services  # noqa: F401

    assert "faster_whisper" not in sys.modules
