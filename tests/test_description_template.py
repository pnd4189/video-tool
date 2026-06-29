import json
from pathlib import Path
from types import SimpleNamespace

from videotool.core import services
from videotool.package.youtube import format_chapters_block, render_description_template


def test_render_template_replaces_all_placeholders() -> None:
    template = "T\n{{RECAP_PREV}}\n{{SUMMARY}}\nChapters:\n{{CHAPTERS}}\nEnd"
    out = render_description_template(
        template,
        chapters_block="00:00 Chương 1: A\n10:00 Chương 2: B",
        recap_prev="Tóm tắt tập trước.",
        summary="Tóm tắt tập này.",
    )
    assert "{{" not in out
    assert "Tóm tắt tập trước." in out
    assert "Tóm tắt tập này." in out
    assert "00:00 Chương 1: A" in out


def test_render_template_empty_values_collapse() -> None:
    out = render_description_template("a{{RECAP_PREV}}b{{SUMMARY}}c{{CHAPTERS}}d", chapters_block="", recap_prev="", summary="")
    assert out == "abcd"


def test_format_chapters_block_formats_timestamps() -> None:
    block = format_chapters_block([(0.0, "Chương 1: A"), (605.0, "Chương 2: B"), (3725.0, "Chương 3: C")])
    assert block == "00:00 Chương 1: A\n10:05 Chương 2: B\n01:02:05 Chương 3: C"


def _template_job(tmp_path: Path) -> Path:
    (tmp_path / "media").mkdir()
    (tmp_path / "voice.wav").write_bytes(b"fake")
    (tmp_path / "media" / "scene-001.png").write_bytes(b"fake")
    (tmp_path / "template.txt").write_text(
        "Tiêu đề tập\n\nTÓM TẮT TẬP TRƯỚC\n{{RECAP_PREV}}\n\nTÓM TẮT TẬP\n{{SUMMARY}}\n\nMỐC THỜI GIAN\n{{CHAPTERS}}\n",
        encoding="utf-8",
    )
    job_path = tmp_path / "job.yaml"
    job_path.write_text(
        """
version: 1
project:
  title: tap
  description: Tóm tắt tập này.
  recap_previous: Tóm tắt tập trước.
inputs:
  voice: voice.wav
  media_dir: media
  description_template: template.txt
outputs:
  - preset: youtube-16x9
storyboard:
  - scene: 1
    image: media/scene-001.png
    duration: 2.0
assets:
  policy: allow-missing-local
package:
  write_srt: false
""",
        encoding="utf-8",
    )
    return job_path


def test_run_package_renders_template_with_chapters_json(tmp_path: Path, monkeypatch) -> None:
    job_path = _template_job(tmp_path)
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "youtube-16x9.mp4").write_bytes(b"fake")
    (output_dir / "thumbnail-1280x720.jpg").write_bytes(b"fake")
    (output_dir / "chapters.json").write_text(
        json.dumps([{"start": 0.0, "title": "Chương 11: A"}, {"start": 600.0, "title": "Chương 12: B"}]),
        encoding="utf-8",
    )
    # Skip ffprobe-heavy validation/thumbnail work; we only assert the description rendering.
    monkeypatch.setattr(services, "validate_package", lambda *a, **k: [])
    monkeypatch.setattr(services, "_generate_thumbnails", lambda *a, **k: None)

    services.run_package(job_path)

    text = (output_dir / "description.txt").read_text(encoding="utf-8")
    assert "{{" not in text
    assert "Tóm tắt tập trước." in text
    assert "Tóm tắt tập này." in text
    assert "00:00 Chương 11: A" in text
    assert "10:00 Chương 12: B" in text


def test_run_package_offsets_chapters_by_intro_cta(tmp_path: Path, monkeypatch) -> None:
    # chapters.json is narration-aligned; with an intro CTA the published timestamps shift by
    # its duration and a 00:00 "Giới thiệu" marker is prepended.
    job_path = _template_job(tmp_path)
    text = job_path.read_text(encoding="utf-8").replace(
        "  description_template: template.txt",
        "  description_template: template.txt\n  intro_cta: intro.mp4",
    )
    job_path.write_text(text, encoding="utf-8")
    (tmp_path / "intro.mp4").write_bytes(b"fake")
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    (output_dir / "youtube-16x9.mp4").write_bytes(b"fake")
    (output_dir / "thumbnail-1280x720.jpg").write_bytes(b"fake")
    (output_dir / "chapters.json").write_text(
        json.dumps([{"start": 0.0, "title": "Chương 11: A"}, {"start": 600.0, "title": "Chương 12: B"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(services, "validate_package", lambda *a, **k: [])
    monkeypatch.setattr(services, "_generate_thumbnails", lambda *a, **k: None)
    monkeypatch.setattr(services, "probe_media", lambda *a, **k: SimpleNamespace(duration=8.0))

    services.run_package(job_path)

    desc = (output_dir / "description.txt").read_text(encoding="utf-8")
    assert "00:00 Giới thiệu" in desc
    assert "00:08 Chương 11: A" in desc  # shifted by the 8s intro CTA
    assert "10:08 Chương 12: B" in desc
