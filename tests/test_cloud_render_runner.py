"""Resume-path artifact re-materialization for the cloud render runner.

A resume re-stages the source folder (wiping the local job dir) but skips cloud_director
(the pinned job.yaml short-circuits it), so the cheap artifacts prepare_job/apply_creative
created — the ``media/`` dir and ``outputs/captions.srt`` — are gone. render's path
validation then fails with "Path does not exist: /tmp/job/media" (the Chap 25 ver19 crash).
``_ensure_prepare_artifacts`` re-materializes them every render so a resume can proceed.
"""

from __future__ import annotations

import pytest
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


def _parallax_job(tmp_path: Path, stills: int, clips: int) -> Path:
    scenes = "".join(f"- {{scene: {i}, image: img{i}.jpg, duration: 10}}\n" for i in range(stills))
    (tmp_path / "job.yaml").write_text(
        f"enhance: {{parallax: true}}\nstoryboard:\n{scenes}", encoding="utf-8"
    )
    if clips:
        (tmp_path / "Parallax").mkdir()
        for i in range(clips):
            (tmp_path / "Parallax" / f"img{i}.mp4").write_bytes(b"x")
    return tmp_path / "job.yaml"


def test_parallax_guard_passes_when_every_still_is_linked(tmp_path: Path) -> None:
    # parallax-link already swapped the stills for clips -> nothing left for on-box depth.
    job_yaml = _parallax_job(tmp_path, stills=0, clips=120)
    rr._check_parallax_source(tmp_path, job_yaml, None)


def test_parallax_guard_aborts_when_prerendered_clips_are_missing(tmp_path: Path) -> None:
    # A missing Parallax/ used to silently trigger hours of on-box depth work (Chap 18).
    job_yaml = _parallax_job(tmp_path, stills=109, clips=0)
    with pytest.raises(rr.RunnerError, match="Parallax/"):
        rr._check_parallax_source(tmp_path, job_yaml, None)


def test_parallax_guard_allows_explicit_on_box_opt_in(tmp_path: Path) -> None:
    job_yaml = _parallax_job(tmp_path, stills=109, clips=0)
    creative = tmp_path / "creative.yaml"
    creative.write_text("enhance:\n  parallax_on_box: true\n", encoding="utf-8")
    rr._check_parallax_source(tmp_path, job_yaml, creative)


def test_parallax_guard_ignores_jobs_without_parallax(tmp_path: Path) -> None:
    (tmp_path / "job.yaml").write_text("enhance: {}\nstoryboard: []\n", encoding="utf-8")
    rr._check_parallax_source(tmp_path, tmp_path / "job.yaml", None)


def _job_with_srt(tmp_path: Path) -> Path:
    (tmp_path / "Dao_Si_Quen_0027_0028_vi_qa.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nXin chào.\n", encoding="utf-8"
    )
    (tmp_path / "job.yaml").write_text("render: {encoder: h264_nvenc-capped}\n", encoding="utf-8")
    return tmp_path


def test_ensure_prepare_artifacts_creates_media_dir_on_resume(tmp_path: Path, monkeypatch) -> None:
    # Simulates a resume: source re-staged, but the media/ dir prepare_job made is gone.
    job = _job_with_srt(tmp_path)
    assert not (job / "media").exists()

    monkeypatch.setattr(rr.vc, "_run_cli", lambda args: None)
    rr._ensure_prepare_artifacts(job)

    assert (job / "media").is_dir()  # render's path validation needs this to exist


def test_ensure_prepare_artifacts_rematerializes_captions_from_qa_srt(tmp_path: Path, monkeypatch) -> None:
    job = _job_with_srt(tmp_path)
    assert not (job / "outputs" / "captions.srt").exists()

    monkeypatch.setattr(rr.vc, "_run_cli", lambda args: None)
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


def test_ensure_prepare_artifacts_keeps_existing_captions(tmp_path: Path, monkeypatch) -> None:
    # A first run (not a resume) already wrote captions.srt — do not clobber it.
    job = _job_with_srt(tmp_path)
    outputs = job / "outputs"
    outputs.mkdir()
    (outputs / "captions.srt").write_text("KEEP-ME", encoding="utf-8")

    monkeypatch.setattr(rr.vc, "_run_cli", lambda args: None)
    rr._ensure_prepare_artifacts(job)

    assert (outputs / "captions.srt").read_text(encoding="utf-8") == "KEEP-ME"


def test_bitrate_cap_selects_the_lower_vbv_variant(tmp_path: Path) -> None:
    # A 2.6h episode at the default 2800k ceiling overshoots the size budget; creative.yaml pins
    # the lower-ceiling variant of whatever encoder the box probed.
    creative = tmp_path / "creative.yaml"
    creative.write_text("render:\n  bitrate_cap: 2500k\n", encoding="utf-8")
    assert rr._bitrate_cap(creative) == "2500k"
    assert rr._apply_bitrate_cap("h264_nvenc-capped", "2500k") == "h264_nvenc-capped-2500k"


def test_bitrate_cap_2200k_for_3h_plus_episodes(tmp_path: Path) -> None:
    # A ~3.8h (226 min) episode overshoots even the raised 4.5 GB budget at 2500k (~4.6 GB), so
    # Claude pins the 2200k VBV variant. Probed encoder is the CPU profile on the TPU box.
    from videotool.render.profiles import PROFILES

    creative = tmp_path / "creative.yaml"
    creative.write_text("render:\n  bitrate_cap: 2200k\n", encoding="utf-8")
    assert rr._bitrate_cap(creative) == "2200k"
    assert rr._apply_bitrate_cap("libx264-balanced-capped", "2200k") == "libx264-balanced-capped-2200k"
    assert "libx264-balanced-capped-2200k" in PROFILES
    assert "h264_nvenc-capped-2200k" in PROFILES


def test_bitrate_cap_absent_keeps_the_probed_profile(tmp_path: Path) -> None:
    creative = tmp_path / "creative.yaml"
    creative.write_text("enhance:\n  sfx:\n    pack: binh-thien\n", encoding="utf-8")
    assert rr._bitrate_cap(creative) is None
    assert rr._apply_bitrate_cap("h264_nvenc-capped", None) == "h264_nvenc-capped"


def test_unknown_bitrate_cap_aborts_before_gpu_time() -> None:
    with pytest.raises(rr.RunnerError):
        rr._apply_bitrate_cap("h264_nvenc-capped", "9999k")


def test_resume_accepts_a_capped_variant_of_the_probed_encoder(monkeypatch) -> None:
    # Resume re-probes only to confirm the environment; the pinned encoder carries a `-2500k`
    # suffix the probe never returns, so equality would abort a perfectly valid resume.
    monkeypatch.setattr(rr, "probe_encoder", lambda allow_cpu=False: "h264_nvenc-capped")
    rr._assert_encoder_supported("h264_nvenc-capped-2500k")


def test_ensure_prepare_artifacts_rederives_chapters_on_resume(tmp_path: Path, monkeypatch) -> None:
    # outputs/chapters.json feeds the {{CHAPTERS}} block in the published description. prepare_job
    # derives it and a resume skips prepare_job, so without this the episode publishes with no
    # chapter timestamps — and chapters-from-srt fails quietly, so nothing would flag it.
    job = _job_with_srt(tmp_path)
    calls: list[list[str]] = []
    monkeypatch.setattr(rr.vc, "_run_cli", lambda args: calls.append(args))

    rr._ensure_prepare_artifacts(job)

    assert calls == [["chapters-from-srt", str(job / "job.yaml")]]


def test_ensure_prepare_artifacts_keeps_existing_chapters(tmp_path: Path, monkeypatch) -> None:
    job = _job_with_srt(tmp_path)
    (job / "outputs").mkdir()
    (job / "outputs" / "chapters.json").write_text("[]", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(rr.vc, "_run_cli", lambda args: calls.append(args))

    rr._ensure_prepare_artifacts(job)

    assert calls == []
