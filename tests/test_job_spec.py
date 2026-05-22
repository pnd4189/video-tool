from pathlib import Path

import pytest

from videotool.core.job_spec import JobSpec, load_job


def test_valid_basic_job_loads() -> None:
    job = load_job(Path("examples/jobs/basic-audio-first/job.yaml"))
    assert job.project.title == "sample-video"
    assert [item.preset for item in job.outputs] == ["youtube-16x9", "shorts-9x16"]


def test_unknown_preset_has_clear_error() -> None:
    with pytest.raises(ValueError, match="Unknown preset"):
        JobSpec.model_validate(
            {
                "version": 1,
                "project": {"title": "bad"},
                "inputs": {"voice": "voice.wav"},
                "outputs": [{"preset": "square"}],
            }
        )


def test_invalid_schema_version_rejected() -> None:
    with pytest.raises(ValueError, match="schema version"):
        JobSpec.model_validate(
            {
                "version": 2,
                "project": {"title": "bad"},
                "inputs": {"voice": "voice.wav"},
            }
        )


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        JobSpec.model_validate(
            {
                "version": 1,
                "project": {"title": "bad", "typo": True},
                "inputs": {"voice": "voice.wav"},
            }
        )


def test_burn_in_caption_mode_is_supported() -> None:
    job = JobSpec.model_validate(
        {
            "version": 1,
            "project": {"title": "captioned"},
            "inputs": {"voice": "voice.wav"},
            "captions": {"mode": "srt-and-burn"},
        }
    )
    assert job.captions.mode == "srt-and-burn"
