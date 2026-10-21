"""The Colab CLI lane driver: session names, CLI output parsing, the VM snippets (run here for real with
a local Python), parted transfers and the submit/watch/fetch flow against a fake VM, run order.

Offline only: no Colab, no Drive.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import signal
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


cr = _load("colab_render")
lane = cr.lane
STATUS = ("[vt-chap-76] m-hm-kkb-use4b1-1whrssytqqbrx | Hardware: CPU | Shape: High-RAM | Variant: DEFAULT"
          " | Status: IDLE")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snippet(code: str, args: dict) -> dict:
    proc = subprocess.run([sys.executable, "-c", cr.script(code, args)], capture_output=True, text=True)
    payload = cr.parse_marker(proc.stdout)
    assert payload is not None, proc.stdout + proc.stderr
    return payload


class FakeVM:
    """`colab` and `remote` against a folder standing in for the VM's disk (remote paths live under
    root); the snippets run for real with a local Python."""

    def __init__(self, root: Path):
        self.root, self.calls, self.fail_once, self.outputs = root, [], set(), {}

    def path(self, remote_path: str) -> Path:
        return self.root / remote_path.lstrip("/")

    def colab(self, *args, timeout=None, check=True):
        self.calls.append(args)
        if args[0] in ("upload", "download"):
            src, dst = args[-2], args[-1]
            if Path(src).name in self.fail_once:
                self.fail_once.discard(Path(src).name)
                raise cr.LaneError(f"{args[0]} of {Path(src).name} failed")
            src_path, dst_path = ((Path(src), self.path(dst)) if args[0] == "upload"
                                  else (self.path(src), Path(dst)))
            if not src_path.is_file() or not dst_path.parent.is_dir():
                raise cr.LaneError(f"File or directory not found: {src} -> {dst}")
            shutil.copy(src_path, dst_path)
            return f"[colab] {args[0]} done"
        return self.outputs.get(args[0], "")

    def remote(self, session, code, args, timeout=None):
        return _snippet(code, {k: str(self.path(v)) if isinstance(v, str) and v.startswith("/content") else v
                               for k, v in args.items()})


@pytest.fixture
def vm(tmp_path, monkeypatch):
    fake = FakeVM(tmp_path / "vm")
    monkeypatch.setattr(cr, "colab", fake.colab)
    monkeypatch.setattr(cr, "remote", fake.remote)
    monkeypatch.setattr(cr, "PART_BYTES", 1000)
    monkeypatch.setattr(cr.time, "sleep", lambda seconds: None)
    return fake


# --- names and parsing -----------------------------------------------------------------------------

def test_session_name_is_prefixed_folded_and_short():
    assert cr.session_name("binh-thien-chap76") == "vt-binh-thien-chap76"
    long = cr.session_name("Bình Thiên Sách — Chương 76 đến 80, bản đầy đủ có phụ đề vàng")
    assert long.startswith("vt-binh-thien-sach-chuong-76") and len(long) <= cr.MAX_SESSION_LEN
    assert long.isascii() and not long.endswith("-")


def test_marker_is_the_last_marker_line():
    assert cr.parse_marker('noise\nVTCOLAB {"a": 1}\n[colab] chatter\nVTCOLAB {"a": 2}\n') == {"a": 2}
    assert cr.parse_marker("Traceback (most recent call last):\nRuntimeError: boom") is None
    assert cr.parse_marker("VTCOLAB {not json") is None


def test_status_line_of_this_session_is_parsed():
    out = "[vt-other] m-s-1 | Hardware: CPU | Shape: Standard | Variant: DEFAULT | Status: BUSY\n" + STATUS
    assert cr.parse_session_line(out, "vt-chap-76") == {
        "endpoint": "m-hm-kkb-use4b1-1whrssytqqbrx", "hardware": "CPU", "shape": "High-RAM",
        "variant": "DEFAULT", "status": "IDLE"}
    assert cr.parse_session_line(out, "vt-chap-7") is None


def test_balance_is_read_from_colab_usage():
    assert cr.parse_balance("Current balance: 199.96 compute units\nUsage rate: 0.00/hr") == 199.96
    assert cr.parse_balance("[colab] not logged in") is None


def test_startup_lines_wait_for_render_start():
    tail = ["[    0.1s] box: python 3.13.16 | 8 cpu | 50.1 GiB RAM", "pip noise", "[   12.0s] encoder pinned: x"]
    assert cr.startup_lines(tail) is None
    tail.append("[   12.1s] render start (8 scene workers, 9 scenes)")
    assert cr.startup_lines(tail) == [tail[0], tail[2], tail[3]]


def test_shared_steps_use_this_lanes_state_file_and_tag(capsys):
    assert lane.STATE_NAME == ".colab-cpu.json"
    assert lane.bundle_excluded(".colab-cpu.json") and not lane.bundle_excluded("job.yaml")
    cr.say("hello")
    assert capsys.readouterr().out.startswith("[colab ")


def test_box_folders_follow_the_colab_env(monkeypatch):
    monkeypatch.setenv("VT_BOX_INPUT", "/content/vt-in")
    monkeypatch.setenv("VT_BOX_WORK", "/content/vt-out")
    box = _load("kaggle_cpu_box")
    assert (box.INPUT_ROOT, box.WORK) == (Path("/content/vt-in"), Path("/content/vt-out"))
    monkeypatch.delenv("VT_BOX_INPUT")
    monkeypatch.delenv("VT_BOX_WORK")
    assert _load("kaggle_cpu_box").WORK == Path("/kaggle/working")


# --- snippets, run here for real -------------------------------------------------------------------

def test_parts_cut_here_join_on_the_vm(tmp_path):
    data = bytes(range(256)) * 10
    (tmp_path / "a.bin").write_bytes(data)
    parts = cr.split_file(tmp_path / "a.bin", tmp_path / "a.parts", part_bytes=1000)
    assert [p.stat().st_size for p in parts] == [1000, 1000, 560]
    joined = _snippet(cr.JOIN, {"parts": str(tmp_path / "a.parts"), "dest": str(tmp_path / "b.bin")})
    assert joined == {"parts": 3, "bytes": 2560, "sha256": _sha(data)}
    assert not (tmp_path / "a.parts").exists()


def _box(tmp_path: Path, body: str) -> Path:
    box = tmp_path / "in/box.py"
    box.parent.mkdir(parents=True, exist_ok=True)
    box.write_text(body)
    return box


def _launch(tmp_path: Path, box: Path) -> dict:
    return _snippet(cr.LAUNCH, {"in": str(box.parent), "out": str(tmp_path / "out"), "box": str(box)})


def _keep(out: Path, grace: float = 0, part_bytes: int = 1000) -> dict:
    """Run the keeper cell here until the box ends and its grace runs out; the status.json it leaves."""
    _snippet(cr.KEEP, {"out": str(out), "every": 0.2, "part_bytes": part_bytes, "grace": grace,
                       "grace_failed": 0})
    return json.loads((out / "status.json").read_text())


def test_keeper_waits_for_the_detached_box_and_reports_its_result(tmp_path):
    box = _box(tmp_path, (
        "import json, os, time\n"
        "print('[    0.1s] heartbeat: 1/2 clips', flush=True)\n"
        "time.sleep(2)\n"
        "with open(os.path.join(os.environ['VT_BOX_WORK'], 'result.json'), 'w') as fh:\n"
        "    json.dump({'status': 'complete', 'input': os.environ['VT_BOX_INPUT']}, fh)\n"))
    launched = _launch(tmp_path, box)
    started = time.time()
    status = _keep(tmp_path / "out")
    assert launched["pid"] > 0 and time.time() - started > 1.5  # the cell stayed busy until the box ended
    assert status["ended"] and status["exit"] == 0 and status["beat"] > 2
    assert status["result"] == {"status": "complete", "input": str(box.parent)}
    assert status["tail"] == ["[    0.1s] heartbeat: 1/2 clips"]
    assert {"box.log", "box.exit", "box.pid", "result.json"} <= set(status["files"]) and status["parts"] == {}


def _ended_box(out: Path, files: dict[str, bytes], exit_code: int = 0) -> None:
    """The out folder of a box that already ended: no such pid, its exit code, its files."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "box.pid").write_text("999999999")
    (out / "box.exit").write_text(f"{exit_code}\n")
    for name, data in files.items():
        (out / name).write_bytes(data)


def test_keeper_cuts_big_files_and_holds_the_vm_through_the_grace(tmp_path):
    mp4 = bytes(range(256)) * 10
    _ended_box(tmp_path / "out", {"x.mp4": mp4, "job.yaml": b"x: 1\n", "box.log": b"l" * 3000,
                                  "result.json": json.dumps({"status": "complete", "mp4": "x.mp4"}).encode()})
    started = time.time()
    status = _keep(tmp_path / "out", grace=1)
    assert time.time() - started >= 1 and status["ended"] and status["beat"] > 3
    assert status["parts"] == {"x.mp4": [["p.0000", 1000], ["p.0001", 1000], ["p.0002", 560]]}
    parts = sorted((tmp_path / "out/x.mp4.parts").iterdir())
    assert b"".join(p.read_bytes() for p in parts) == mp4 and not (tmp_path / "out/box.log.parts").exists()


def test_keeper_reports_a_box_that_failed(tmp_path):
    _launch(tmp_path, _box(tmp_path, "import sys\nprint('[    0.1s] box: python', flush=True)\nsys.exit(3)\n"))
    status = _keep(tmp_path / "out", grace=60)  # a failed box gets grace_failed (0 here), not grace
    assert status["ended"] and status["exit"] == 3 and status["result"] is None
    assert status["tail"] == ["[    0.1s] box: python"]


def test_keeper_ends_when_the_box_vanished_without_an_exit_code(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out/box.pid").write_text("999999999")
    status = _keep(tmp_path / "out")
    assert status["ended"] and status["exit"] is None and status["result"] is None


def test_launch_clears_the_end_of_an_earlier_box(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for name in ("box.exit", "result.json", "status.json"):
        (out / name).write_text("0")
    launched = _launch(tmp_path, _box(tmp_path, "import time\ntime.sleep(30)\n"))
    try:
        assert not any((out / name).exists() for name in ("box.exit", "result.json", "status.json"))
        assert (out / "box.pid").read_text() == str(launched["pid"])
    finally:
        os.killpg(launched["pid"], signal.SIGTERM)


def test_start_keeper_holds_the_cell_in_a_detached_colab_exec(tmp_path, monkeypatch):
    old = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "colab", "vt-chap-76"],
                           start_new_session=True)
    stage = _running_stage(tmp_path, keeper_pid=old.pid)
    started = []

    class Popen:
        def __init__(self, cmd, **kwargs):
            started.append((cmd, kwargs))
            self.pid = 4321

    monkeypatch.setattr(cr.subprocess, "Popen", Popen)
    monkeypatch.setattr(cr, "colab_exe", lambda: "/usr/bin/colab")
    cr.start_keeper(stage)
    cell = tmp_path / "chap-76-colab/keeper.py"
    (cmd, kwargs), = started
    assert cmd == ["/usr/bin/colab", "--config", str(cr.SESSION_CONFIG), "exec", "-s", "vt-chap-76", "-f", str(cell),
                   "--timeout", str(cr.SESSION_CAP_S)]
    assert kwargs["start_new_session"] and kwargs["stdin"] is subprocess.DEVNULL
    assert "status.json" in cell.read_text() and lane.load_state(stage)["keeper_pid"] == 4321
    assert old.wait(timeout=10) == -signal.SIGTERM  # the restart stopped the process it replaced


def test_stop_keeper_ends_only_its_own_colab_exec():
    nap = [sys.executable, "-c", "import time; time.sleep(30)"]
    mine = subprocess.Popen([*nap, "colab", "vt-chap-76"], start_new_session=True)
    other = subprocess.Popen([*nap, "vt-chap-76"], start_new_session=True)
    try:
        cr.stop_keeper({"keeper_pid": mine.pid, "session": "vt-chap-76"})
        cr.stop_keeper({"keeper_pid": other.pid, "session": "vt-chap-76"})
        cr.stop_keeper({"session": "vt-chap-76"})
        assert mine.wait(timeout=10) == -signal.SIGTERM
        assert other.poll() is None
    finally:
        for proc in (mine, other):
            proc.kill()
            proc.wait()


# --- parted transfers ------------------------------------------------------------------------------

def test_push_sends_parts_and_checks_the_join_on_the_vm(tmp_path, vm):
    data = b"x" * 2500
    (tmp_path / "bundle.vtb").write_bytes(data)
    cr.push("vt-s", tmp_path / "bundle.vtb", "/content/vt-in/bundle.vtb", _sha(data), tmp_path / "parts")
    assert vm.path("/content/vt-in/bundle.vtb").read_bytes() == data
    assert not vm.path("/content/vt-in/bundle.vtb.parts").exists() and not (tmp_path / "parts").exists()
    assert sum(call[0] == "upload" for call in vm.calls) == 3


def test_push_retries_a_part_that_failed_once(tmp_path, vm):
    data = b"y" * 2500
    (tmp_path / "bundle.vtb").write_bytes(data)
    vm.fail_once = {"p.0001"}
    cr.push("vt-s", tmp_path / "bundle.vtb", "/content/vt-in/bundle.vtb", _sha(data), tmp_path / "parts")
    assert vm.path("/content/vt-in/bundle.vtb").read_bytes() == data
    assert sum(call[0] == "upload" for call in vm.calls) == 4


def test_push_refuses_a_bundle_that_arrived_different(tmp_path, vm):
    (tmp_path / "bundle.vtb").write_bytes(b"z" * 2500)
    with pytest.raises(cr.LaneError, match="arrived as 2500 bytes"):
        cr.push("vt-s", tmp_path / "bundle.vtb", "/content/vt-in/bundle.vtb", "0" * 64, tmp_path / "parts")


def _vm_file(vm: FakeVM, name: str, data: bytes) -> list | None:
    """Put a file in the fake VM's out folder, cut into parts beside it the way the keeper does."""
    path = vm.path(f"/content/vt-out/{name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if len(data) <= cr.PART_BYTES:
        return None
    parts = cr.split_file(path, path.parent / f"{name}.parts")
    return [[p.name, p.stat().st_size] for p in parts]


def test_pull_takes_small_files_whole_and_big_ones_from_the_keepers_parts(tmp_path, vm):
    small, big = b"s" * 900, bytes(range(256)) * 12
    assert _vm_file(vm, "small.json", small) is None
    parts = _vm_file(vm, "big.mp4", big)
    cr.pull("vt-s", "/content/vt-out/small.json", 900, tmp_path / "dl/small.json")
    cr.pull("vt-s", "/content/vt-out/big.mp4", len(big), tmp_path / "dl/big.mp4", sha256=_sha(big), parts=parts)
    assert (tmp_path / "dl/small.json").read_bytes() == small and (tmp_path / "dl/big.mp4").read_bytes() == big
    assert not (tmp_path / "dl/big.mp4.parts").exists()
    assert sum(call[0] == "download" for call in vm.calls) == 1 + 4


def test_pull_refuses_a_big_file_the_keeper_did_not_cut(tmp_path, vm):
    _vm_file(vm, "big.mp4", b"m" * 3000)
    with pytest.raises(cr.LaneError, match="not cut into parts"):
        cr.pull("vt-s", "/content/vt-out/big.mp4", 3000, tmp_path / "dl/big.mp4")


def test_pull_refuses_a_file_whose_sha_differs(tmp_path, vm):
    parts = _vm_file(vm, "big.mp4", b"m" * 3000)
    with pytest.raises(cr.LaneError, match="sha256 differs"):
        cr.pull("vt-s", "/content/vt-out/big.mp4", 3000, tmp_path / "dl/big.mp4", sha256="0" * 64, parts=parts)


# --- submit ----------------------------------------------------------------------------------------

def _prepared(tmp_path: Path, monkeypatch) -> Path:
    stage = tmp_path / "chap-76"
    (stage / "outputs").mkdir(parents=True)
    (stage / "job.yaml").write_text("storyboard:\n  - scene: 1\n  - scene: 2\n")
    monkeypatch.setattr(lane, "preflight", lambda stage, hours: (5.0, 3600.0, 7.0))

    def build_bundle(stage: Path, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "bundle.vtb").write_bytes(b"B" * 2500)
        return out_dir / "bundle.vtb", _sha(b"B" * 2500)

    monkeypatch.setattr(lane, "build_bundle", build_bundle)
    monkeypatch.setattr(lane, "run", lambda cmd, **kw: "abc123")
    return stage


def test_dry_run_starts_no_vm(tmp_path, monkeypatch, capsys):
    stage = _prepared(tmp_path, monkeypatch)
    monkeypatch.setattr(cr, "colab", lambda *a, **kw: pytest.fail(f"colab called: {a}"))
    cr.submit(stage, "chap-76", 3.5, dry_run=True, force=False)
    out = capsys.readouterr().out
    assert '"session": "vt-chap-76"' in out and '"stop_after_s": 38700' in out and "no VM created" in out
    assert not (stage / lane.STATE_NAME).exists()


def test_submit_uploads_launches_and_records_the_run(tmp_path, monkeypatch, vm):
    stage = _prepared(tmp_path, monkeypatch)
    vm.outputs = {"usage": "Current balance: 150.00 compute units", "status": STATUS}
    launched = []

    def remote(session, code, args, timeout=None):
        if code is cr.LAUNCH:
            launched.append(args)
            return {"pid": 4242, "python": "3.13.16"}
        return vm.remote(session, code, args, timeout)

    monkeypatch.setattr(cr, "remote", remote)
    keepers = []
    monkeypatch.setattr(cr, "start_keeper", keepers.append)
    cr.submit(stage, "chap-76", 3.5, dry_run=False, force=False)
    state = lane.load_state(stage)
    assert (state["status"], state["endpoint"], state["box_pid"]) == ("running", "m-hm-kkb-use4b1-1whrssytqqbrx", 4242)
    assert keepers == [stage]
    assert vm.path("/content/vt-in/bundle.vtb").read_bytes() == b"B" * 2500
    assert json.loads(vm.path("/content/vt-in/manifest.json").read_text())["stop_after_s"] == 38_700
    assert vm.path("/content/vt-in/kaggle_cpu_box.py").read_text() == lane.BOX_SCRIPT.read_text()
    assert ("new", "-s", "vt-chap-76", "--high-mem") in vm.calls
    assert launched == [{"in": "/content/vt-in", "out": "/content/vt-out", "box": "/content/vt-in/kaggle_cpu_box.py"}]
    assert not any(call[0] == "stop" for call in vm.calls)


def test_submit_stops_a_vm_that_is_not_high_ram(tmp_path, monkeypatch, vm):
    stage = _prepared(tmp_path, monkeypatch)
    vm.outputs = {"usage": "Current balance: 150.00 compute units", "status": STATUS.replace("High-RAM", "Standard")}
    with pytest.raises(cr.LaneError, match="not a high-RAM CPU VM"):
        cr.submit(stage, "chap-76", 3.5, dry_run=False, force=False)
    assert ("stop", "-s", "vt-chap-76") in vm.calls
    assert lane.load_state(stage)["status"] == "failed" and lane.load_state(stage)["cleaned"]


def test_submit_stops_the_vm_when_the_upload_fails(tmp_path, monkeypatch, vm):
    stage = _prepared(tmp_path, monkeypatch)
    vm.outputs = {"usage": "Current balance: 150.00 compute units", "status": STATUS}

    def push(*args):
        raise cr.LaneError("network down")

    monkeypatch.setattr(cr, "push", push)
    with pytest.raises(cr.LaneError, match="network down"):
        cr.submit(stage, "chap-76", 3.5, dry_run=False, force=False)
    assert ("stop", "-s", "vt-chap-76") in vm.calls


def test_submit_needs_compute_units(tmp_path, monkeypatch, vm):
    stage = _prepared(tmp_path, monkeypatch)
    vm.outputs = {"usage": "Current balance: 2.00 compute units"}
    with pytest.raises(cr.LaneError, match="under 5.0"):
        cr.submit(stage, "chap-76", 3.5, dry_run=False, force=False)
    assert not any(call[0] == "new" for call in vm.calls)


# --- watch / fetch / cleanup -----------------------------------------------------------------------

def _running_stage(tmp_path: Path, **extra) -> Path:
    stage = tmp_path / "chap-76"
    (stage / "outputs").mkdir(parents=True)
    (tmp_path / "chap-76-colab").mkdir()
    state = {"session": "vt-chap-76", "endpoint": "m-hm-1", "status": "running", "bundle_sha256": "b" * 64,
             "vm_started_at": time.time(), "submitted_at": time.time(), "balance_before": 150.0,
             "bundle_dir": str(tmp_path / "chap-76-colab"), **extra}
    (stage / lane.STATE_NAME).write_text(json.dumps(state))
    return stage


def _status(beat: int, ended: bool = False, exit=None, result=None, tail=(), files=None) -> dict:
    return {"beat": beat, "ended": ended, "exit": exit, "tail": list(tail), "files": files or {}, "result": result}


def _flow(monkeypatch, statuses: list, sessions: str = "[colab] No active sessions found on server.") -> list:
    calls, queue = [], list(statuses)

    def read_status(stage):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def colab(*args, timeout=None, check=True):
        calls.append(args)
        return {"sessions": sessions, "usage": "Current balance: 149.00 compute units",
                "stop": "[colab] Session terminated."}.get(args[0], "")

    monkeypatch.setattr(cr, "read_status", read_status)
    monkeypatch.setattr(cr, "colab", colab)
    monkeypatch.setattr(cr, "start_keeper", lambda stage: calls.append(("start_keeper",)))
    monkeypatch.setattr(cr.time, "sleep", lambda seconds: None)
    return calls


def test_watch_waits_for_the_box_and_records_its_end(tmp_path, monkeypatch, capsys):
    stage = _running_stage(tmp_path)
    boot = ["[    0.2s] box: python 3.13.16 | 8 cpu | 50.1 GiB RAM", "[    9.0s] render start (8 scene workers, 12 scenes)"]
    calls = _flow(monkeypatch, [_status(1, tail=boot), _status(5, tail=boot),
                                _status(9, ended=True, exit=0, result={"status": "complete"})])
    cr.watch(stage)
    state = lane.load_state(stage)
    assert state["status"] == "complete" and not state.get("cleaned")
    out = capsys.readouterr().out
    assert out.count("render start") == 1 and "render COMPLETE on Colab" in out
    assert not any(call[0] in ("stop", "start_keeper") for call in calls)


def test_a_failed_box_keeps_its_logs_and_stops_the_vm(tmp_path, monkeypatch):
    stage = _running_stage(tmp_path)
    calls = _flow(monkeypatch, [_status(3, ended=True, exit=1, tail=["[    3.0s] boom"], files={"box.log": 10})])
    with pytest.raises(cr.LaneError, match="the box exited 1"):
        cr.watch(stage)
    state = lane.load_state(stage)
    assert state["status"] == "failed" and state["cleaned"] and state["balance_after"] == 149.0
    assert ("download", "-s", "vt-chap-76", "/content/vt-out/box.log", str(tmp_path / "chap-76-colab/box.log")) in calls
    assert ("stop", "-s", "vt-chap-76") in calls


def test_a_box_that_vanished_without_an_exit_code_fails(tmp_path, monkeypatch):
    stage = _running_stage(tmp_path)
    _flow(monkeypatch, [_status(4, ended=True)])
    with pytest.raises(cr.LaneError, match="gone without an exit code"):
        cr.watch(stage)


def test_a_stalled_keeper_is_started_again(tmp_path, monkeypatch):
    stage = _running_stage(tmp_path)
    stalled = [None] * cr.STALE_POLLS
    calls = _flow(monkeypatch, [*stalled, _status(6, ended=True, exit=0, result={"status": "complete"})],
                  sessions="vt-chap-76 m-hm-1 CPU")
    cr.watch(stage)
    assert calls.count(("start_keeper",)) == 1 and lane.load_state(stage)["status"] == "complete"


def test_a_stalled_keeper_on_a_vanished_vm_means_lost(tmp_path, monkeypatch):
    stage = _running_stage(tmp_path)
    _flow(monkeypatch, [_status(2)] * (cr.STALE_POLLS + 1))
    with pytest.raises(cr.LaneError, match="Colab reclaimed the VM"):
        cr.watch(stage)
    assert lane.load_state(stage)["status"] == "lost"


def test_a_vm_colab_reclaimed_is_reported_lost(tmp_path, monkeypatch):
    stage = _running_stage(tmp_path)
    _flow(monkeypatch, [cr.LaneError("no answer")] * cr.MAX_FAILED_POLLS)
    with pytest.raises(cr.LaneError, match="Colab reclaimed the VM"):
        cr.watch(stage)
    assert lane.load_state(stage)["status"] == "lost"


def test_a_silent_vm_that_is_still_listed_is_left_running(tmp_path, monkeypatch):
    stage = _running_stage(tmp_path)
    calls = _flow(monkeypatch, [cr.LaneError("no answer")] * cr.MAX_FAILED_POLLS, sessions="vt-chap-76 m-hm-1 CPU")
    with pytest.raises(cr.LaneError, match="re-run `watch`"):
        cr.watch(stage)
    assert not any(call[0] == "stop" for call in calls) and lane.load_state(stage)["status"] == "running"


def test_cleanup_refuses_to_stop_a_vm_before_the_download(tmp_path, monkeypatch):
    stage = _running_stage(tmp_path)
    calls = _flow(monkeypatch, [])
    with pytest.raises(cr.LaneError, match="not downloaded yet"):
        cr.cleanup(stage, force=False)
    cr.cleanup(stage, force=True)
    assert ("stop", "-s", "vt-chap-76") in calls and lane.load_state(stage)["cleaned"]


def _finished_vm(vm: FakeVM, mp4: bytes, bundle_sha: str) -> None:
    """The fake VM after a complete box, its status.json and parts written by the real keeper cell."""
    result = {"status": "complete", "mp4": "Tập 76.mp4", "bytes": len(mp4), "sha256": _sha(mp4),
              "bundle_sha256": bundle_sha, "render_seconds": 3600.0, "cpu_count": 8}
    _ended_box(vm.path("/content/vt-out"), {"Tập 76.mp4": mp4, "result.json": json.dumps(result).encode(),
                                            "job.yaml": b"x: 1\n", "logs.tar": b"t" * 10})
    _keep(vm.path("/content/vt-out"))
    vm.outputs = {"sessions": "[colab] No active sessions found on server.",
                  "usage": "Current balance: 148.50 compute units"}


def test_fetch_downloads_checks_and_stops_the_vm(tmp_path, vm):
    stage = _running_stage(tmp_path, status="complete")
    mp4 = b"m" * 2600
    _finished_vm(vm, mp4, "b" * 64)
    cr.fetch(stage)
    dl = tmp_path / "chap-76-dl"
    assert (dl / "Tập 76.mp4").read_bytes() == mp4 and (dl / "job.yaml").exists() and (dl / "logs.tar").exists()
    state = lane.load_state(stage)
    assert state["fetched"] and state["cleaned"] and state["result"]["mp4"] == "Tập 76.mp4"
    assert ("stop", "-s", "vt-chap-76") in vm.calls


def test_fetch_refuses_the_result_of_another_submission(tmp_path, vm):
    stage = _running_stage(tmp_path, status="complete")
    _finished_vm(vm, b"m" * 2600, "c" * 64)
    with pytest.raises(cr.LaneError, match="another submission"):
        cr.fetch(stage)
    assert not any(call[0] == "stop" for call in vm.calls)


# --- CLI -------------------------------------------------------------------------------------------

def test_submit_refuses_an_open_run(tmp_path, capsys):
    stage = _running_stage(tmp_path)
    assert cr.main(["submit", str(stage)]) == 1
    assert "already has a run" in capsys.readouterr().out


def test_run_and_publish_need_a_remote(tmp_path, capsys):
    assert cr.main(["run", str(tmp_path)]) == 1
    assert "--remote is required" in capsys.readouterr().out


def test_run_renders_then_finishes_publishes_and_purges(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(cr, "submit", lambda *args: order.append("submit"))
    for name in ("watch", "fetch"):
        monkeypatch.setattr(cr, name, lambda stage, name=name: order.append(name))
    monkeypatch.setattr(lane, "finish", lambda stage: order.append("finish"))
    monkeypatch.setattr(lane, "publish", lambda stage, remote: order.append(f"publish {remote}"))
    monkeypatch.setattr(lane, "purge", lambda stage: order.append("purge"))
    assert cr.main(["run", str(tmp_path / "chap-76"), "--remote", "gdrive:a/Chap 76"]) == 0
    assert order == ["submit", "watch", "fetch", "finish", "publish gdrive:a/Chap 76", "purge"]
