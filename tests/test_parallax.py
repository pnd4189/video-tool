from pathlib import Path
from types import SimpleNamespace

import pytest

from videotool.core import services
from videotool.core.errors import DependencyError
from videotool.core.job_spec import EnhanceSpec, JobSpec
from videotool.core.timeline import compile_timeline
from videotool.core.presets import get_preset
from videotool.render import parallax


def test_parallax_default_off_and_independent_of_tier() -> None:
    assert EnhanceSpec().parallax is False
    # tier=full enables overlay features but must NOT silently enable expensive parallax.
    assert EnhanceSpec(tier="full").parallax is False
    assert EnhanceSpec(parallax=True).parallax is True


def test_clip_path_is_stable_and_duration_sensitive(tmp_path: Path) -> None:
    img = tmp_path / "scene.png"
    img.write_bytes(b"fake-bytes")
    preset = SimpleNamespace(width=1920, height=1080, fps=30)
    a = parallax._clip_path(tmp_path, img, 6.0, preset)
    b = parallax._clip_path(tmp_path, img, 6.0, preset)
    c = parallax._clip_path(tmp_path, img, 7.0, preset)
    assert a == b           # same inputs -> same cache file (reuse across runs)
    assert a != c           # different duration -> different clip
    assert a.suffix == ".mp4" and a.parent == tmp_path


def test_parallaxize_raises_clear_error_without_extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallax, "parallax_available", lambda: False)
    job = JobSpec.model_validate(
        {
            "version": 1,
            "project": {"title": "p"},
            "inputs": {"voice": "voice.wav", "media_dir": "media"},
            "outputs": [{"preset": "youtube-16x9"}],
            "storyboard": [{"scene": 1, "image": "media/a.png", "duration": 6.0}],
            "assets": {"policy": "allow-missing-local"},
        }
    )
    timeline = compile_timeline(job, tmp_path / "job.yaml", duration=6.0)
    with pytest.raises(DependencyError, match="enhance.parallax needs extra"):
        parallax.parallaxize_timeline(timeline, tmp_path / "cache", get_preset("youtube-16x9"))


def test_dry_run_render_skips_parallax_materialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # enhance.parallax on + dry-run must produce plans WITHOUT importing torch / rendering clips,
    # proving the dry-run guard never triggers the expensive parallax pass.
    (tmp_path / "media").mkdir()
    (tmp_path / "voice.wav").write_bytes(b"fake")
    (tmp_path / "media" / "a.png").write_bytes(b"fake")
    (tmp_path / "job.yaml").write_text(
        """
version: 1
project:
  title: parallax
inputs:
  voice: voice.wav
  media_dir: media
outputs:
  - preset: youtube-16x9
enhance:
  parallax: true
captions:
  mode: "off"
storyboard:
  - scene: 1
    image: media/a.png
    duration: 4.0
assets:
  policy: allow-missing-local
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(services, "probe_media", lambda path: SimpleNamespace(duration=4.0))
    result = services.run_render(tmp_path / "job.yaml", dry_run=True)
    assert len(result) == 1
    # Still scene kept as image with zoompan in the dry-run plan (no parallax clip swapped in).
    assert "zoompan" in " ".join(result[0].command)
