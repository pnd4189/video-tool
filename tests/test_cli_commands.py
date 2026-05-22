from pathlib import Path

from typer.testing import CliRunner

from videotool.cli.main import app


def test_validate_reports_missing_files_for_example_job() -> None:
    result = CliRunner().invoke(app, ["validate", "examples/jobs/basic-audio-first/job.yaml"])
    assert result.exit_code != 0
    assert "Path does not exist" in result.output


def test_init_job_creates_template(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["init-job", str(tmp_path), "--voice", "voice.wav"])
    assert result.exit_code == 0
    assert (tmp_path / "job.yaml").exists()


def test_unknown_render_preset_fails(tmp_path: Path) -> None:
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        """
version: 1
project:
  title: test
inputs:
  voice: voice.wav
  media_dir: media
outputs:
  - preset: youtube-16x9
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    (tmp_path / "voice.wav").write_bytes(b"not real media")
    (tmp_path / "media").mkdir()
    result = CliRunner().invoke(app, ["render", str(job_path), "--preset", "typo", "--dry-run"])
    assert result.exit_code != 0
    assert "Requested preset" in result.output


def test_burn_subtitle_mode_requires_srt(tmp_path: Path) -> None:
    job_path = tmp_path / "job.yaml"
    (tmp_path / "media").mkdir()
    (tmp_path / "voice.wav").write_bytes(b"not real media")
    job_path.write_text(
        """
version: 1
project:
  title: burn
inputs:
  voice: voice.wav
  media_dir: media
outputs:
  - preset: youtube-16x9
captions:
  mode: srt-and-burn
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["render", str(job_path), "--dry-run"])
    assert result.exit_code != 0
    assert "captions.srt is missing" in result.output
