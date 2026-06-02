from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from videotool.cli import commands
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


def test_render_enhance_flag_overrides_job_tier(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_run_render(job_path, selected, *, dry_run=False, enhance_tier=None):
        captured["job_path"] = job_path
        captured["selected"] = selected
        captured["dry_run"] = dry_run
        captured["enhance_tier"] = enhance_tier
        return [SimpleNamespace(command=["ffmpeg"], output_path=tmp_path / "out.mp4", preset="youtube-16x9")]

    monkeypatch.setattr(commands, "run_render", fake_run_render)
    job_path = tmp_path / "job.yaml"
    job_path.write_text("version: 1\nproject:\n  title: x\ninputs:\n  voice: voice.wav\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["render", str(job_path), "--enhance", "full", "--dry-run"])

    assert result.exit_code == 0
    assert captured["enhance_tier"] == "full"
    assert captured["dry_run"] is True
