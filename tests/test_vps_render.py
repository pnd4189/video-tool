"""The VPS lane driver: readiness rules, the VPS snippets (run here for real with a local Python, a temp
folder standing in for the VPS home) and the submit/watch/fetch flow against a fake box, run order.

Offline only: no ssh, no Drive.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/make-video/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vr = _load("vps_render")
lane = vr.lane

READY_INFO = {"load1": 0.1, "free_gb": 110.0, "holder": None, "ffmpeg": True, "python": True}

FAKE_BOX = r'''
import hashlib, io, json, os, sys, tarfile, time
inp, work = os.environ["VT_BOX_INPUT"], os.environ["VT_BOX_WORK"]
manifest = json.load(open(os.path.join(inp, "manifest.json")))
print("[    0.0s] box: python fake | 2 cpu", flush=True)
print("[    0.1s] render start (2 scene workers, 3 scenes, no stop)", flush=True)
time.sleep(float(os.environ.get("FAKE_BOX_SLEEP", "0.3")))
print("[    1.0s] heartbeat: 3/3 clips, 0 min", flush=True)
mp4 = b"video" * 1000
open(os.path.join(work, "youtube-16x9.mp4"), "wb").write(mp4)
open(os.path.join(work, "job.yaml"), "w").write("storyboard: []\n")
with tarfile.open(os.path.join(work, "logs.tar"), "w") as tar:
    data = b"render log"
    info = tarfile.TarInfo("render.log")
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))
json.dump({"status": "complete", "mp4": "youtube-16x9.mp4", "bytes": len(mp4),
           "sha256": hashlib.sha256(mp4).hexdigest(), "bundle_sha256": manifest["bundle_sha256"],
           "render_seconds": 1.0, "cpu_count": 2, "path": os.environ["PATH"].split(os.pathsep)[0]},
          open(os.path.join(work, "result.json"), "w"))
sys.exit(int(os.environ.get("FAKE_BOX_EXIT", "0")))
'''


def _run_snippet(code: str, *args: str, cwd: Path) -> dict:
    proc = subprocess.run([sys.executable, "-c", code, *args], capture_output=True, text=True, cwd=cwd, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return vr.parse_json_line(proc.stdout)


def _wait_for(path: Path, seconds: float = 15) -> str:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


class FakeVPS:
    """ssh/scp against a temp home: snippets run for real with this Python, `mkdir` runs locally, copies are
    file copies. The VPS python is this one; its ffmpeg folder is a stand-in."""

    def __init__(self, home: Path):
        self.home, self.copies_to, self.load1 = home, [], 0.1
        (home / vr.FFMPEG_BIN).mkdir(parents=True)
        (home / vr.FFMPEG_BIN / "ffmpeg").write_text("#!/bin/sh\n")
        (home / vr.FFMPEG_BIN / "ffmpeg").chmod(0o755)
        (home / vr.PYTHON).parent.mkdir(parents=True)
        (home / vr.PYTHON).symlink_to(sys.executable)

    def snippet(self, code, *args, timeout=None):
        out = _run_snippet(code, *args, cwd=self.home)
        if code is vr.READY:  # the real snippet reads this machine's load; the fake VPS sets its own
            out["load1"] = self.load1
        return out

    def ssh(self, *argv, timeout=None):
        assert argv[:2] == ("mkdir", "-p"), argv
        for path in argv[2:]:
            (self.home / path).mkdir(parents=True, exist_ok=True)
        return ""

    def copy_to(self, local, remote_dir):
        self.copies_to.append([p.name for p in local])
        for path in local:
            shutil.copy(path, self.home / remote_dir / path.name)

    def copy_from(self, remote_path, local):
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.home / remote_path, local)


@pytest.fixture
def vps(tmp_path, monkeypatch):
    fake = FakeVPS(tmp_path / "home")
    for name in ("snippet", "ssh", "copy_to", "copy_from"):
        monkeypatch.setattr(vr, name, getattr(fake, name))
    monkeypatch.setattr(vr, "BOX_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.setattr(vr, "POLL_S", 0.2)
    box = tmp_path / "kaggle_cpu_box.py"
    box.write_text(FAKE_BOX)
    monkeypatch.setattr(lane, "BOX_SCRIPT", box)
    return fake


def _stage(tmp_path: Path, monkeypatch) -> Path:
    stage = tmp_path / "binh-thien-chap82"
    (stage / "outputs").mkdir(parents=True)
    (stage / "job.yaml").write_text("storyboard: [{image: a.jpg}, {image: b.jpg}, {image: c.jpg}]\n")
    monkeypatch.setattr(lane, "preflight", lambda s, h: (8.76, 14211.5, 14.69))

    def bundle(s, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "bundle.vtb").write_bytes(b"bundle")
        return out_dir / "bundle.vtb", hashlib.sha256(b"bundle").hexdigest()

    monkeypatch.setattr(lane, "build_bundle", bundle)
    monkeypatch.setattr(lane, "run", lambda cmd, cwd=None, check=True: "abc123")
    return stage


# --- pure rules ------------------------------------------------------------------------------------

def test_shared_steps_use_this_lanes_own_state_file_and_tag(capsys):
    assert lane.STATE_NAME == ".vps.json"
    assert lane.bundle_excluded(".vps.json")
    vr.say("hello")
    assert capsys.readouterr().out.startswith("[vps ")


def test_job_dir_is_slugified_under_jobs():
    assert vr.job_dir("Bình Thiên Chap 82") == f"{vr.JOBS}/binh-thien-chap-82"
    with pytest.raises(lane.LaneError):
        vr.job_dir("!!!")


def test_ready_vps_passes():
    vr.check_ready(READY_INFO, "binh-thien-chap82", force=False)


@pytest.mark.parametrize("change, force, words", [
    ({"ffmpeg": False}, True, "set it up"),
    ({"holder": "ke-tru-ta-chap09"}, True, "one render at a time"),
    ({"holder": "binh-thien-chap82"}, False, "already has a job"),
    ({"load1": 1.8}, False, "busy"),
    ({"free_gb": 12.0}, True, "GB free"),
])
def test_vps_that_cannot_take_a_render_is_refused(change, force, words):
    with pytest.raises(lane.LaneError, match=words):
        vr.check_ready({**READY_INFO, **change}, "binh-thien-chap82", force=force)


def test_force_takes_over_a_busy_vps_and_this_episodes_own_job():
    vr.check_ready({**READY_INFO, "load1": 1.8, "holder": "binh-thien-chap82"}, "binh-thien-chap82", force=True)


def test_snippet_answer_is_the_last_json_line():
    assert vr.parse_json_line('pip noise\n{"a": 1}\n') == {"a": 1}
    with pytest.raises(lane.LaneError):
        vr.parse_json_line("Traceback ...")


def test_no_narration_cap_by_default(monkeypatch):
    seen = {}
    monkeypatch.setattr(vr, "submit", lambda stage, slug, hours, dry, force: seen.update(hours=hours))
    assert vr.main(["submit", "/tmp/x", "--dry-run"]) == 0
    assert seen["hours"] == float("inf")


# --- the VPS snippets, run here for real -----------------------------------------------------------

def test_lock_admits_one_job_at_a_time(tmp_path):
    (tmp_path / vr.JOBS).mkdir(parents=True)
    assert _run_snippet(vr.TAKE, vr.LOCK, "a", cwd=tmp_path) == {"taken": True, "holder": "a"}
    assert _run_snippet(vr.TAKE, vr.LOCK, "b", cwd=tmp_path) == {"taken": False, "holder": "a"}
    ready = _run_snippet(vr.READY, vr.JOBS, vr.LOCK, "nope/ffmpeg", "nope/python", cwd=tmp_path)
    assert ready["holder"] == "a" and ready["ffmpeg"] is False and ready["free_gb"] > 0


def test_launch_returns_at_once_and_the_box_outlives_it(tmp_path):
    job = tmp_path / "jobs/x"
    (job / "in").mkdir(parents=True)
    (job / "in/box.py").write_text("import os, time\ntime.sleep(1.5)\n"
                                   "open('env.txt', 'w').write(os.environ['VT_BOX_WORK'] + '|' + os.environ['PATH'])\n"
                                   "raise SystemExit(3)\n")
    scratch = tmp_path / "scratch"
    (scratch / "old").mkdir(parents=True)
    started = time.time()
    launched = _run_snippet(vr.LAUNCH, "jobs/x", sys.executable, "ffbin", "box.py", str(scratch), cwd=tmp_path)
    assert time.time() - started < 1.5 and launched["pid"] > 0
    assert not scratch.exists()  # a stale unpack never mixes into the new render
    assert _wait_for(job / "work/box.exit") == "3"
    work, path = (job / "work/env.txt").read_text().split("|")
    assert work == str(job / "work") and path.startswith(str(tmp_path / "ffbin"))


def test_probe_reads_the_end_and_result_of_the_box(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    (work / "box.log").write_text("[    0.1s] render start\n[    5.0s] heartbeat: 1/2 clips\n")
    assert _run_snippet(vr.PROBE, "w", cwd=tmp_path)["exit"] is None
    (work / "box.exit").write_text("0\n")
    (work / "box.pid").write_text("999999999")
    (work / "result.json").write_text('{"status": "complete"}')
    probe = _run_snippet(vr.PROBE, "w", cwd=tmp_path)
    assert probe["exit"] == 0 and probe["alive"] is False and probe["result"] == {"status": "complete"}
    assert probe["tail"][-1].endswith("1/2 clips") and probe["files"]["box.log"] > 0


def test_clean_stops_the_box_and_frees_only_what_this_job_holds(tmp_path):
    job, scratch = tmp_path / "jobs/x", tmp_path / "scratch"
    (job / "in").mkdir(parents=True)
    scratch.mkdir()
    (job / "in/box.py").write_text("import time\ntime.sleep(60)\n")
    pid = _run_snippet(vr.LAUNCH, "jobs/x", sys.executable, "ff", "box.py", str(tmp_path / "other"),
                       cwd=tmp_path)["pid"]
    (tmp_path / "jobs/.lock").write_text("someone-else")
    out = _run_snippet(vr.CLEAN, "jobs/x", "jobs/.lock", "x", str(scratch), "1", cwd=tmp_path)
    assert out == {"killed": pid, "released": False, "holder": "someone-else"}
    assert not job.exists() and scratch.exists() and (tmp_path / "jobs/.lock").exists()
    deadline = time.time() + 5
    while os.path.exists(f"/proc/{pid}") and time.time() < deadline:
        time.sleep(0.05)
    assert not os.path.exists(f"/proc/{pid}")
    (tmp_path / "jobs/.lock").write_text("x")
    (tmp_path / "jobs/x").mkdir()
    out = _run_snippet(vr.CLEAN, "jobs/x", "jobs/.lock", "x", str(scratch), "0", cwd=tmp_path)
    assert out["released"] and not scratch.exists() and not (tmp_path / "jobs/.lock").exists()


# --- the flow against a fake VPS -------------------------------------------------------------------

def test_dry_run_uploads_nothing(tmp_path, monkeypatch, vps, capsys):
    stage = _stage(tmp_path, monkeypatch)
    vr.submit(stage, stage.name, float("inf"), dry_run=True, force=False)
    assert vps.copies_to == [] and not (vps.home / vr.LOCK).exists()
    manifest = json.loads((tmp_path / "binh-thien-chap82-vps/manifest.json").read_text())
    assert manifest["stop_after_s"] is None and manifest["scenes"] == 3
    assert "dry run" in capsys.readouterr().out


def test_submit_watch_fetch_render_and_free_the_vps(tmp_path, monkeypatch, vps, capsys):
    stage = _stage(tmp_path, monkeypatch)
    vr.submit(stage, stage.name, float("inf"), dry_run=False, force=False)
    state = lane.load_state(stage)
    assert state["status"] == "running" and (vps.home / vr.LOCK).read_text() == "binh-thien-chap82"
    assert vps.copies_to == [["bundle.vtb", "manifest.json", "kaggle_cpu_box.py"]]
    vr.watch(stage)
    assert lane.load_state(stage)["status"] == "complete"
    vr.fetch(stage)
    state = lane.load_state(stage)
    dl = tmp_path / "binh-thien-chap82-dl"
    assert state["fetched"] and state["cleaned"] and (dl / "youtube-16x9.mp4").exists()
    assert state["result"]["path"] == str(vps.home / vr.FFMPEG_BIN)  # the box ran with the static ffmpeg first
    assert not (vps.home / state["job_dir"]).exists() and not (vps.home / vr.LOCK).exists()
    out = capsys.readouterr().out
    assert "box started on" in out and "render COMPLETE on the VPS" in out and "sha256 ok" in out


def test_a_second_episode_waits_for_the_vps(tmp_path, monkeypatch, vps):
    stage = _stage(tmp_path, monkeypatch)
    (vps.home / vr.JOBS).mkdir(parents=True)
    (vps.home / vr.LOCK).write_text("ke-tru-ta-chap09")
    with pytest.raises(lane.LaneError, match="one render at a time"):
        vr.submit(stage, stage.name, float("inf"), dry_run=False, force=True)
    assert vps.copies_to == []


def test_a_failed_box_keeps_its_logs_and_frees_the_vps(tmp_path, monkeypatch, vps):
    monkeypatch.setenv("FAKE_BOX_EXIT", "2")
    stage = _stage(tmp_path, monkeypatch)
    vr.submit(stage, stage.name, float("inf"), dry_run=False, force=False)
    with pytest.raises(lane.LaneError, match="the box exited 2"):
        vr.watch(stage)
    state = lane.load_state(stage)
    assert state["status"] == "failed" and state["cleaned"]
    assert (tmp_path / "binh-thien-chap82-vps/box.log").exists() and not (vps.home / vr.LOCK).exists()


def test_fetch_refuses_the_result_of_another_submission(tmp_path, monkeypatch, vps):
    stage = _stage(tmp_path, monkeypatch)
    vr.submit(stage, stage.name, float("inf"), dry_run=False, force=False)
    vr.watch(stage)
    lane.save_state(stage, {**lane.load_state(stage), "bundle_sha256": "other"})
    with pytest.raises(lane.LaneError, match="no result of this submission"):
        vr.fetch(stage)
    assert (vps.home / vr.LOCK).exists()  # nothing fetched, nothing freed


def test_cleanup_refuses_to_delete_a_render_not_downloaded(tmp_path, monkeypatch, vps):
    monkeypatch.setenv("FAKE_BOX_SLEEP", "30")
    stage = _stage(tmp_path, monkeypatch)
    vr.submit(stage, stage.name, float("inf"), dry_run=False, force=False)
    with pytest.raises(lane.LaneError, match="not downloaded yet"):
        vr.cleanup(stage, force=False)
    vr.cleanup(stage, force=True)
    state = lane.load_state(stage)
    assert state["cleaned"] and state["status"] == "cancelled" and not (vps.home / vr.LOCK).exists()


def test_submit_refuses_an_open_run(tmp_path, monkeypatch, vps):
    stage = _stage(tmp_path, monkeypatch)
    lane.save_state(stage, {"submitted_at": 1.0, "status": "running"})
    with pytest.raises(lane.LaneError, match="already has a run"):
        vr.submit(stage, stage.name, float("inf"), dry_run=False, force=False)


def test_run_and_publish_need_a_remote(tmp_path, capsys):
    assert vr.main(["run", str(tmp_path)]) == 1
    assert "--remote is required" in capsys.readouterr().out


def test_run_renders_then_finishes_publishes_and_purges(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(vr, "submit", lambda *a: order.append("submit"))
    for name in ("watch", "fetch"):
        monkeypatch.setattr(vr, name, lambda s, n=name: order.append(n))
    monkeypatch.setattr(lane, "finish", lambda s: order.append("finish"))
    monkeypatch.setattr(lane, "publish", lambda s, r: order.append(f"publish {r}"))
    monkeypatch.setattr(lane, "purge", lambda s: order.append("purge"))
    assert vr.main(["run", str(tmp_path), "--remote", "gdrive:x/Chap 82"]) == 0
    assert order == ["submit", "watch", "fetch", "finish", "publish gdrive:x/Chap 82", "purge"]
