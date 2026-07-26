"""Resume-path artifact re-materialization for the cloud render runner.

A resume re-stages the source folder (wiping the local job dir) but skips cloud_director
(the pinned job.yaml short-circuits it), so the cheap artifacts prepare_job/apply_creative
created — the ``media/`` dir and ``outputs/captions.srt`` — are gone. render's path
validation then fails with "Path does not exist: /tmp/job/media" (the Chap 25 ver19 crash).
``_ensure_prepare_artifacts`` re-materializes them every render so a resume can proceed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Colab"))

import cloud_render_runner as rr  # noqa: E402


def test_nvenc_probe_frame_clears_min_dimensions(monkeypatch) -> None:
    # A 64x64 probe frame makes NVENC InitializeEncoder fail 'Frame Dimension less than the minimum
    # supported value' on a working T4 — a false negative that aborts every GPU render. Guard that
    # the probe frame stays safely above the H.264 NVENC minimum (145x49).
    import re

    seen: dict[str, tuple[int, int]] = {}

    class _Res:
        returncode = 0
        stderr = ""

    def fake_run(args, check=False):
        joined = " ".join(args)
        m = re.search(r"s=(\d+)x(\d+)", joined)
        if m and "h264_nvenc" in joined:
            seen["dims"] = (int(m.group(1)), int(m.group(2)))
        return _Res()

    monkeypatch.setattr(rr, "_run", fake_run)
    assert rr._nvenc_can_encode() is True
    w, h = seen["dims"]
    assert w >= 145 and h >= 49


def _job_with_srt(tmp_path: Path) -> Path:
    (tmp_path / "Dao_Si_Quen_0027_0028_vi_qa.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nXin chào.\n", encoding="utf-8"
    )
    (tmp_path / "job.yaml").write_text("render: {encoder: h264_nvenc-capped}\n", encoding="utf-8")
    return tmp_path


def test_ensure_prepare_artifacts_creates_media_dir_on_resume(tmp_path: Path) -> None:
    # Simulates a resume: source re-staged, but the media/ dir prepare_job made is gone.
    job = _job_with_srt(tmp_path)
    assert not (job / "media").exists()

    rr._ensure_prepare_artifacts(job)

    assert (job / "media").is_dir()  # render's path validation needs this to exist


def test_ensure_prepare_artifacts_rematerializes_captions_from_qa_srt(tmp_path: Path) -> None:
    job = _job_with_srt(tmp_path)
    assert not (job / "outputs" / "captions.srt").exists()

    rr._ensure_prepare_artifacts(job)

    captions = job / "outputs" / "captions.srt"
    assert captions.is_file()
    assert "Xin chào." in captions.read_text(encoding="utf-8")


def test_ensure_prepare_artifacts_restages_overlay_on_resume(tmp_path: Path) -> None:
    # apply_creative copies the overlay into the job root on the first run and pins
    # inputs.particle_overlay = its bare filename. A resume skips cloud_director, so the file is
    # gone and render's path validation aborts ("Path does not exist: fireflies-gen-01.mp4").
    job = tmp_path / "job"
    job.mkdir()
    (job / "job.yaml").write_text(
        "inputs: {particle_overlay: fireflies-gen-01.mp4}\n", encoding="utf-8"
    )
    library = tmp_path / "overlays"
    library.mkdir()
    (library / "fireflies-gen-01.mp4").write_bytes(b"overlay-bytes")

    rr._ensure_prepare_artifacts(job, overlay_library=library)

    restaged = job / "fireflies-gen-01.mp4"
    assert restaged.is_file()
    assert restaged.read_bytes() == b"overlay-bytes"


def test_ensure_prepare_artifacts_keeps_existing_captions(tmp_path: Path) -> None:
    # A first run (not a resume) already wrote captions.srt — do not clobber it.
    job = _job_with_srt(tmp_path)
    outputs = job / "outputs"
    outputs.mkdir()
    (outputs / "captions.srt").write_text("KEEP-ME", encoding="utf-8")

    rr._ensure_prepare_artifacts(job)

    assert (outputs / "captions.srt").read_text(encoding="utf-8") == "KEEP-ME"
