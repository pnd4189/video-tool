from pathlib import Path

from videotool.core.services import run_init_job, run_validate


def test_init_then_validate_without_existing_files(tmp_path: Path) -> None:
    job_path = run_init_job(tmp_path, "voice.wav", "media", None)
    errors = run_validate(job_path, require_existing=False)
    assert any("Asset index is required" in error for error in errors)
