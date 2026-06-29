from pathlib import Path
from types import SimpleNamespace

from videotool.core import services
from videotool.core.job_spec import load_job


def _job(tmp_path: Path, extra_inputs: str = "", extra_blocks: str = "") -> Path:
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        f"""
version: 1
project:
  title: t
inputs:
  voice: voice.wav
  media_dir: media
{extra_inputs}outputs:
  - preset: youtube-16x9
storyboard:
  - scene: 1
    image: media/s.png
    duration: 2.0
assets:
  policy: allow-missing-local
{extra_blocks}""",
        encoding="utf-8",
    )
    return job_path


def test_stage_subtitle_shifts_burn_copy_by_intro_cta(tmp_path: Path) -> None:
    job_path = _job(tmp_path, extra_blocks="enhance:\n  subtitles: true\n")
    job = load_job(job_path)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "captions.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8"
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cta = services._CtaRender(
        voice_path=tmp_path / "voice-cta.flac",
        intro_seconds=8.0,
        outro_seconds=0.0,
        intro_image=None,
        outro_image=None,
    )
    staged = services._stage_subtitle(job, job_path, workspace, cta)
    assert staged is not None
    text = staged.read_text(encoding="utf-8")
    # Burn copy shifted by the 8s intro CTA; the on-disk source stays narration-aligned.
    assert "00:00:08,000 --> 00:00:10,000" in text
    assert "00:00:00,000" in (outputs / "captions.srt").read_text(encoding="utf-8")


def test_stage_voice_cta_uses_clip_as_visual_fallback(tmp_path: Path, monkeypatch) -> None:
    job_path = _job(
        tmp_path,
        extra_inputs="  intro_cta: intro.mp4\n  outro_cta: outro.mp4\n",
    )
    job = load_job(job_path)
    monkeypatch.setattr(
        services,
        "compose_voice",
        lambda *a, **k: SimpleNamespace(
            path=tmp_path / "ws" / "voice-cta.flac", intro_seconds=8.0, outro_seconds=10.0
        ),
    )
    (tmp_path / "ws").mkdir()
    cta = services._stage_voice_cta(job, job_path, tmp_path / "ws")
    assert cta is not None
    # No explicit cta image -> the animated CTA clip itself becomes the visual.
    assert cta.intro_image is not None and cta.intro_image.name == "intro.mp4"
    assert cta.outro_image is not None and cta.outro_image.name == "outro.mp4"
