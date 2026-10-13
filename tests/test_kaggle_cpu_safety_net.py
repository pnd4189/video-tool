"""Kaggle CPU lane: faster baked render settings and the safety net at Kaggle's session wall.

Offline: no Kaggle, no ffmpeg render — the Kaggle CLI and the local render are replaced by functions
that write the files they would produce.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tarfile
import time
from pathlib import Path

import pytest
import yaml

from videotool.render.profiles import PROFILES

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/make-video/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kcpu = _load("kaggle_cpu_render")
box = _load("kaggle_cpu_box")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _job_yaml(path: Path, *, cta: bool = True) -> Path:
    inputs = {"voice": "voice.wav", "media_dir": "media"}
    if cta:
        inputs.update(intro_cta="CTA voice/intro.mp4", outro_cta="CTA voice/outro.mp4")
    data = {"version": 1, "inputs": inputs, "render": {"encoder": "h264_nvenc-capped"},
            "storyboard": [{"scene": i, "image": f"Image/{i}.jpg", "duration": 2.0} for i in range(1, 4)]}
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_clip_total_counts_the_cta_cards(tmp_path: Path) -> None:
    assert box.clip_total(_job_yaml(tmp_path / "with.yaml")) == 5
    assert box.clip_total(_job_yaml(tmp_path / "without.yaml", cta=False)) == 3


def test_box_pins_the_faster_profile_with_overlays_baked(tmp_path: Path) -> None:
    job = _job_yaml(tmp_path / "job.yaml")
    box.pin_render(job, "libx264-faster-capped-2500k")
    data = yaml.safe_load(job.read_text(encoding="utf-8"))
    assert data["render"] == {"encoder": "libx264-faster-capped-2500k", "bake_overlays": True}
    assert len(data["storyboard"]) == 3
    for cap in ("", "-2500k", "-2200k"):
        assert box.require_cpu_encoder(f"{box.CPU_PROFILE}{cap}") in PROFILES


def _clips(job: Path, names: list[str]) -> Path:
    clips = job / ".videotool/tmp/clips/youtube-16x9"
    clips.mkdir(parents=True)
    for name in names:
        (clips / name).write_bytes(name.encode())
    return clips


def test_ship_clips_sends_finished_clips_only(tmp_path: Path) -> None:
    job = tmp_path / "job"
    _clips(job, ["scene-0000.mp4", "scene-0001.mp4", "scene-0002.part.mp4", "notes.txt"])
    shipped = box.ship_clips(job, tmp_path / "clips.tar")
    with tarfile.open(tmp_path / "clips.tar") as tar:
        names = tar.getnames()
    assert names == ["clips/youtube-16x9/scene-0000.mp4", "clips/youtube-16x9/scene-0001.mp4"]
    assert shipped["clips_done"] == 2 and shipped["sha256"] == _sha(tmp_path / "clips.tar")


def test_ship_clips_refuses_when_the_output_disk_is_too_small(tmp_path: Path, monkeypatch) -> None:
    job = tmp_path / "job"
    _clips(job, ["scene-0000.mp4"])
    monkeypatch.setattr(box, "free_gib", lambda path: 0.5)
    with pytest.raises(box.BoxError, match="GiB free"):
        box.ship_clips(job, tmp_path / "clips.tar")


def test_render_is_stopped_at_the_deadline_with_its_children(tmp_path: Path) -> None:
    child = tmp_path / "child.pid"
    proc = subprocess.Popen(["bash", "-c", f"sleep 60 & echo $! > {child}; wait"], start_new_session=True)
    assert box.wait_or_stop(proc, stop_at=time.time() + 1, poll_s=0.2) is None
    pid = int(child.read_text())
    time.sleep(0.2)
    assert subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode != 0  # sleep is gone


def test_a_render_that_ends_in_time_keeps_its_exit_code() -> None:
    proc = subprocess.Popen(["bash", "-c", "exit 3"], start_new_session=True)
    assert box.wait_or_stop(proc, stop_at=time.time() + 60, poll_s=0.2) == 3


def test_manifest_stops_the_box_before_the_kernel_timeout() -> None:
    assert kcpu.KERNEL_TIMEOUT_S - kcpu.STOP_MARGIN_S == 41_400 - 2_700
    assert kcpu.CLIPS_TAR == box.CLIPS_TAR


def test_finished_kernel_json_log_reads_as_plain_text() -> None:
    raw = ('[{"stream_name":"stdout","time":1.0,"data":"[    0.0s] box: python 3.13\\n"}\n'
           ',{"stream_name":"stdout","time":2.0,"data":"[  120.0s] heartbeat: 2/304 clips\\n"}\n]')
    assert kcpu.log_text(raw) == "[    0.0s] box: python 3.13\n[  120.0s] heartbeat: 2/304 clips\n"
    assert kcpu.log_text("[   1.0s] plain line") == "[   1.0s] plain line\n"


def _partial_output(dl: Path, stage_job: Path, bundle_sha: str) -> None:
    """What a box stopped at its deadline leaves in /kaggle/working."""
    dl.mkdir(parents=True, exist_ok=True)
    src = dl.parent / "box-job"
    _clips(src, ["scene-0000.mp4", "scene-0001.mp4"])
    shipped = box.ship_clips(src, dl / "clips.tar")
    box_yaml = yaml.safe_load(stage_job.read_text(encoding="utf-8"))
    box_yaml["render"] = {"encoder": "libx264-faster-capped-2500k", "bake_overlays": True}
    (dl / "job.yaml").write_text(yaml.safe_dump(box_yaml, allow_unicode=True), encoding="utf-8")
    result = {"status": "partial", **shipped, "scenes": 5, "bundle_sha256": bundle_sha,
              "render_seconds": 39_000.0, "cpu_count": 4}
    (dl / "result.json").write_text(json.dumps(result), encoding="utf-8")


def test_fetch_finishes_a_partial_render_on_this_machine(tmp_path: Path, monkeypatch) -> None:
    stage = tmp_path / "ep"
    (stage / "outputs").mkdir(parents=True)
    _job_yaml(stage / "job.yaml")
    kcpu.save_state(stage, {"kernel_id": "me/videotool-cpu-ep-abc123", "status": "complete",
                            "bundle_sha256": "b" * 64})
    calls = []

    def fake_kaggle(*args, check=True):
        _partial_output(Path(args[args.index("-p") + 1]), stage / "job.yaml", "b" * 64)
        return ""

    def fake_run(cmd, cwd=None, check=True):
        calls.append(cmd)
        workspace = stage / ".videotool/tmp/clips/youtube-16x9"
        assert sorted(p.name for p in workspace.iterdir()) == ["scene-0000.mp4", "scene-0001.mp4"]
        assert yaml.safe_load((stage / "job.yaml").read_text())["render"]["bake_overlays"] is True
        for name in ("scene-0002.mp4", "scene-0003.mp4", "scene-0004.mp4"):
            (workspace / name).write_bytes(b"local")
        (stage / "outputs/youtube-16x9.mp4").write_bytes(b"final video")
        return ""

    monkeypatch.setattr(kcpu, "kaggle", fake_kaggle)
    monkeypatch.setattr(kcpu, "run", fake_run)
    kcpu.fetch(stage)
    state = kcpu.load_state(stage)
    result, dl = state["result"], Path(state["dl_dir"])
    assert calls and calls[0][1:3] == ["render", str(stage / "job.yaml")]
    assert result["status"] == "complete" and result["clips_rendered_locally"] == 3
    assert result["sha256"] == _sha(dl / result["mp4"])
    assert not list((stage / "outputs").glob("*.mp4"))  # finish copies it back from the download dir


def test_local_finish_refuses_a_leftover_mp4(tmp_path: Path) -> None:
    stage = tmp_path / "ep"
    (stage / "outputs").mkdir(parents=True)
    (stage / "outputs/old.mp4").write_bytes(b"x")
    with pytest.raises(kcpu.LaneError, match="already holds"):
        kcpu.complete_locally(stage, tmp_path / "dl", {"clips_tar": "clips.tar", "clips_done": 0})
