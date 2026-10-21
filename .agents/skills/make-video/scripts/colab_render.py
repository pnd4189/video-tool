"""Render one episode on a Colab high-RAM CPU VM through the Colab CLI, no browser. Runbook:
references/colab-runbook.md.

The Kaggle CPU lane with Colab as the renderer: the episode is prepared and finished on this machine
and the VM only renders. Nothing secret leaves this machine — the rclone key has full-Drive scope, so
it never goes to Colab. The VM runs the Kaggle lane's box script (kaggle_cpu_box.py) with its input
and output folders under /content. Each episode gets its own VM `vt-<slug>`, recorded in this lane's
own CLI state file so that a bare `colab stop` from another project cannot reach it. The VM is
stopped as soon as the render is downloaded: an idle VM still burns compute units.

Since CLI 0.7.4 no client pings keep a VM alive: the Colab backend keeps it while its kernel is busy
(CLI design doc, 2026-09-25). So a keeper cell waits on the box for the whole render and writes
status.json every 30 s; the driver reads that file over the file API, which answers while the kernel
is busy. When the box ends the keeper cuts the outputs into parts and holds the VM for a fetch grace,
so `fetch` downloads them without `colab exec` and a render survives a driver that was not running.

    .venv/bin/python .agents/skills/make-video/scripts/colab_render.py run STAGE --remote "gdrive:…/Chap NN"

Steps, each re-runnable (state in STAGE/.colab-cpu.json): submit [--dry-run], watch, fetch, finish,
publish --remote, purge, cleanup [--force], status. Run with the repo venv (PyYAML).

Two CLI behaviours shape this file (measured 2026-10-20, CLI 0.7.4): `colab upload/download` send a
file as one base64 JSON body, so big files travel as 64 MiB parts, eight at a time; and `colab exec`
exits 0 even when the code it ran raised, so every snippet run on the VM ends by printing one
`VTCOLAB {json}` line and only that line counts.
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kaggle_cpu_render as lane  # noqa: E402 — preflight, bundle, finish, verify, publish, purge

# The shared steps read their state file and log tag from the module: point them at this lane's own.
lane.STATE_NAME, lane.TAG = ".colab-cpu.json", "colab"
LaneError, say = lane.LaneError, lane.say

SESSION_PREFIX = "vt-"
MAX_SESSION_LEN = 40
# Other projects use this account through the CLI's default state file, where a bare `colab stop`
# stops "the only session". Renders live in their own file so that can never be one of them.
SESSION_CONFIG = Path.home() / ".config/colab-cli/videotool-sessions.json"
BUNDLE_SUFFIX = "-colab"  # STAGE-colab/ holds bundle + manifest (+ box logs of a failed run)
REMOTE_IN = "/content/vt-in"
REMOTE_OUT = "/content/vt-out"
PART_BYTES = 64 * 2**20
TRANSFER_WORKERS = 8  # 1 GiB test 2026-10-20: 8 parts at once up ~15.5 MiB/s, down ~24 MiB/s
PART_ATTEMPTS = 3
REQUIRED_SHAPE = {"hardware": "CPU", "shape": "High-RAM"}
MIN_BALANCE_CU = 5.0  # a high-RAM CPU VM burns 0.26 CU/h (colab usage, 2026-10-20)
SESSION_CAP_S = 12 * 3600  # Colab FAQ 2026-10-20: Pro runs at most 12 h (24 h is Pro+ only)
STOP_AFTER_S = SESSION_CAP_S - 75 * 60  # the box ships its finished clips here (10.75 h, as on Kaggle)
POLL_S = 120
POLL_TIMEOUT_S = 120
LOG_EVERY_S = 600
MAX_FAILED_POLLS = 5
STATUS_EVERY_S = 30  # the keeper cell rewrites status.json this often
STALE_POLLS = 3  # polls without a new status.json before the keeper cell is started again
# After the box ends the keeper holds the VM — and the render on it — this long for the fetch, in case
# the driver is not running then (a VM with an idle kernel gets reclaimed). `fetch` stops it earlier.
FETCH_GRACE_S = 6 * 3600  # ≈ 1.6 CU at most
FAILED_GRACE_S = 3600  # long enough to pull the logs of a failed box
EXEC_TIMEOUT_S = 600  # joining a few GB on the VM takes about a minute
CLI_TIMEOUT_S = 900
MARKER = "VTCOLAB "

# --- snippets run in the VM's kernel (ARGS and done() come from script()) -------------------------

MKDIR = """
import os
os.makedirs(ARGS["dir"], exist_ok=True)
done({"dir": ARGS["dir"]})
"""

JOIN = """
import hashlib, os, shutil
names = sorted(os.listdir(ARGS["parts"]))
with open(ARGS["dest"], "wb") as out:
    for name in names:
        with open(os.path.join(ARGS["parts"], name), "rb") as src:
            shutil.copyfileobj(src, out, 1 << 20)
shutil.rmtree(ARGS["parts"])
digest = hashlib.sha256()
with open(ARGS["dest"], "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        digest.update(chunk)
done({"parts": len(names), "bytes": os.path.getsize(ARGS["dest"]), "sha256": digest.hexdigest()})
"""

# The box runs detached from the kernel, so every exec call returns at once and the render outlives
# it; bash writes box.exit when the box ends, whatever the reason.
LAUNCH = """
import os, shlex, subprocess, sys
out = ARGS["out"]
os.makedirs(out, exist_ok=True)
for name in ("box.exit", "box.pid", "result.json", "status.json"):
    if os.path.exists(os.path.join(out, name)):
        os.remove(os.path.join(out, name))
env = {**os.environ, "VT_BOX_INPUT": ARGS["in"], "VT_BOX_WORK": out, "PYTHONUNBUFFERED": "1"}
q = shlex.quote
cmd = f"{q(sys.executable)} {q(ARGS['box'])} > {q(out + '/box.log')} 2>&1; echo $? > {q(out + '/box.exit')}"
proc = subprocess.Popen(["bash", "-c", cmd], env=env, cwd=out, start_new_session=True,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
with open(os.path.join(out, "box.pid"), "w") as fh:
    fh.write(str(proc.pid))
done({"pid": proc.pid, "python": sys.version.split()[0]})
"""

# Runs in the kernel's foreground until the box ends, then through the fetch grace: the busy kernel is
# what keeps the VM, and the render on it, alive. Files over part_bytes are cut into parts before the
# status says `ended`, so the download needs no `colab exec`.
KEEP = """
import os, shutil, time
out = ARGS["out"]
def read(name):
    path = os.path.join(out, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()
def alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, ValueError):
        return False
def split(name):
    parts = os.path.join(out, name + ".parts")
    shutil.rmtree(parts, ignore_errors=True)
    os.makedirs(parts)
    with open(os.path.join(out, name), "rb") as fh:
        index = 0
        while chunk := fh.read(ARGS["part_bytes"]):
            with open(os.path.join(parts, f"p.{index:04d}"), "wb") as part:
                part.write(chunk)
            index += 1
    return [[n, os.path.getsize(os.path.join(parts, n))] for n in sorted(os.listdir(parts))]
def write(status):
    with open(os.path.join(out, "status.tmp"), "w", encoding="utf-8") as fh:
        json.dump(status, fh)
    os.replace(os.path.join(out, "status.tmp"), os.path.join(out, "status.json"))
pid, beat = int(read("box.pid")), 0
while True:
    code = (read("box.exit") or "").strip()
    ended = code.lstrip("-").isdigit() or not alive(pid)
    beat += 1
    result = read("result.json") if ended else None
    status = {"beat": beat, "ended": False, "exit": int(code) if code.lstrip("-").isdigit() else None,
              "tail": (read("box.log") or "").splitlines()[-40:],
              "files": {n: os.path.getsize(os.path.join(out, n)) for n in sorted(os.listdir(out))
                        if os.path.isfile(os.path.join(out, n))},
              "result": json.loads(result) if result else None, "parts": {}}
    if ended:
        break
    write(status)
    print(f"keeper beat {beat}", flush=True)  # output too, whichever activity the backend counts
    time.sleep(ARGS["every"])
for name, size in status["files"].items():
    if size > ARGS["part_bytes"] and not name.startswith(("status.", "box.")):
        status["parts"][name] = split(name)
status["ended"] = True
until = time.time() + (ARGS["grace"] if status["exit"] == 0 else ARGS["grace_failed"])
while True:
    write(status)
    if time.time() >= until:
        break
    print(f"keeper waits for the fetch, beat {beat}", flush=True)
    time.sleep(ARGS["every"])
    beat += 1
    status["beat"] = beat
done({"beat": beat, "exit": status["exit"]})
"""


# --- pure helpers ---------------------------------------------------------------------------------

def session_name(slug: str) -> str:
    return SESSION_PREFIX + lane.slugify(slug)[:MAX_SESSION_LEN - len(SESSION_PREFIX)].rstrip("-")


def script(code: str, args: dict) -> str:
    """A self-contained program for the VM: ARGS, a done() that prints the marker line, the snippet."""
    return (f"import json\nARGS = json.loads({json.dumps(args)!r})\n"
            f"def done(payload):\n    print({MARKER!r} + json.dumps(payload), flush=True)\n{code}")


def parse_marker(output: str) -> dict | None:
    """The payload of the last marker line; None when the snippet never got that far."""
    for line in reversed(output.splitlines()):
        if line.startswith(MARKER):
            try:
                return json.loads(line[len(MARKER):])
            except ValueError:
                return None
    return None


def parse_session_line(output: str, session: str) -> dict | None:
    """`[vt-x] m-hm-kkb-… | Hardware: CPU | Shape: High-RAM | Variant: DEFAULT | Status: IDLE` (the
    CLI 0.7.4 `status` line) -> {"endpoint", "hardware", "shape", "variant", "status"}."""
    for line in output.splitlines():
        m = re.match(rf"\[{re.escape(session)}\]\s+(\S+)\s*\|(.*)$", line.strip())
        if m:
            fields = (part.split(":", 1) for part in m.group(2).split("|") if ":" in part)
            return {"endpoint": m.group(1), **{k.strip().lower(): v.strip() for k, v in fields}}
    return None


startup_lines = lane.startup_lines


def parse_balance(output: str) -> float | None:
    m = re.search(r"Current balance:\s*([\d.]+)", output)
    return float(m.group(1)) if m else None


def split_file(path: Path, out_dir: Path, part_bytes: int | None = None) -> list[Path]:
    """path cut into numbered parts of part_bytes, in a fresh out_dir."""
    part_bytes = part_bytes or PART_BYTES
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    parts: list[Path] = []
    with path.open("rb") as src:
        while chunk := src.read(part_bytes):
            parts.append(out_dir / f"p.{len(parts):04d}")
            parts[-1].write_bytes(chunk)
    return parts


def join_parts(parts: list[Path], dest: Path) -> None:
    with dest.open("wb") as out:
        for part in parts:
            with part.open("rb") as src:
                shutil.copyfileobj(src, out, 1 << 20)


# --- the Colab CLI --------------------------------------------------------------------------------

def colab_exe() -> str:
    exe = shutil.which("colab") or str(Path.home() / ".local/bin/colab")
    if not Path(exe).exists():
        raise LaneError("`colab` CLI not found — `uv tool install google-colab-cli`, then `colab whoami`")
    return exe


def colab(*args: str, timeout: float = CLI_TIMEOUT_S, check: bool = True) -> str:
    """One CLI call on this lane's state file. stdin is closed: an expired login fails instead of
    waiting for a pasted code."""
    SESSION_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run([colab_exe(), "--config", str(SESSION_CONFIG), *args], capture_output=True,
                              text=True, errors="replace", stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LaneError(f"colab {' '.join(args[:3])} … gave no answer in {timeout:.0f}s") from exc
    out = (proc.stdout + proc.stderr).strip()
    if check and proc.returncode != 0:
        raise LaneError(f"colab {' '.join(args[:3])} … failed (exit {proc.returncode}):\n{out[-2000:]}")
    return out


def remote(session: str, code: str, args: dict, timeout: float = EXEC_TIMEOUT_S) -> dict:
    """Run a snippet on the VM; its marker payload, or LaneError with what the VM printed instead."""
    with tempfile.TemporaryDirectory(prefix="vt-colab-") as tmp:
        path = Path(tmp) / "snippet.py"
        path.write_text(script(code, args), encoding="utf-8")
        out = colab("exec", "-s", session, "-f", str(path), "--timeout", str(timeout), timeout=timeout + 120)
    payload = parse_marker(out)
    if payload is None:
        raise LaneError(f"the VM did not finish the snippet:\n{out[-1500:]}")
    return payload


def endpoint_listed(endpoint: str) -> bool:
    """Whether the account still holds that VM: `colab sessions` lists every server-side assignment."""
    return endpoint in colab("sessions")


def start_keeper(stage: Path) -> None:
    """Run the KEEP cell. The `colab exec` started here only holds the connection, detached from this
    process: if it or this machine goes away, the cell keeps the kernel busy on the VM anyway."""
    state = lane.load_state(stage)
    stop_keeper(state)  # a restart replaces the process this state still tracks
    keep_dir = Path(state["bundle_dir"])
    cell = keep_dir / "keeper.py"
    cell.write_text(script(KEEP, {"out": REMOTE_OUT, "every": STATUS_EVERY_S, "part_bytes": PART_BYTES,
                                  "grace": FETCH_GRACE_S, "grace_failed": FAILED_GRACE_S}), encoding="utf-8")
    SESSION_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with (keep_dir / "keeper.log").open("a", encoding="utf-8") as log:
        proc = subprocess.Popen([colab_exe(), "--config", str(SESSION_CONFIG), "exec", "-s", state["session"],
                                 "-f", str(cell), "--timeout", str(SESSION_CAP_S)],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)
    lane.save_state(stage, {**state, "keeper_pid": proc.pid})


def stop_keeper(state: dict) -> None:
    """End the local `colab exec` of the keeper cell when it still runs and is still ours."""
    pid = state.get("keeper_pid")
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except (OSError, TypeError):
        return
    if "colab" in cmdline and state["session"] in cmdline:
        try:
            os.killpg(pid, signal.SIGTERM)  # start_new_session made it a group leader
        except ProcessLookupError:
            pass


def read_status(stage: Path) -> dict | None:
    """The keeper cell's last status.json, None before it wrote one. The file API answers while the
    kernel is busy with the keeper; `colab exec` would wait behind it."""
    state = lane.load_state(stage)
    local = Path(state["bundle_dir"]) / "status.json"
    try:
        colab("download", "-s", state["session"], f"{REMOTE_OUT}/status.json", str(local), timeout=POLL_TIMEOUT_S)
    except LaneError as exc:
        if "not found" in str(exc):
            return None
        raise
    return json.loads(local.read_text(encoding="utf-8"))


def in_parallel(jobs: list[Callable[[], object]]) -> None:
    """Every job, TRANSFER_WORKERS at a time, each tried PART_ATTEMPTS times; the first job that fails
    every try cancels the ones not started and raises."""
    def attempt(job: Callable[[], object]) -> object:
        for n in range(1, PART_ATTEMPTS + 1):
            try:
                return job()
            except LaneError:
                if n == PART_ATTEMPTS:
                    raise
                time.sleep(5 * n)
        return None

    pool = ThreadPoolExecutor(TRANSFER_WORKERS)
    try:
        for future in as_completed([pool.submit(attempt, job) for job in jobs]):
            future.result()
    finally:
        pool.shutdown(cancel_futures=True)


def push(session: str, local: Path, remote_path: str, sha256: str, work: Path) -> None:
    """Upload a file of any size as parts, join them on the VM and check size and sha256 there."""
    parts = split_file(local, work)
    remote_parts = f"{remote_path}.parts"
    remote(session, MKDIR, {"dir": remote_parts})
    in_parallel([functools.partial(colab, "upload", "-s", session, str(p), f"{remote_parts}/{p.name}")
                 for p in parts])
    joined = remote(session, JOIN, {"parts": remote_parts, "dest": remote_path})
    shutil.rmtree(work)
    size = local.stat().st_size
    if (joined["bytes"], joined["sha256"]) != (size, sha256):
        raise LaneError(f"{remote_path} arrived as {joined['bytes']} bytes, sha256 {joined['sha256'][:12]}; "
                        f"sent {size} bytes, sha256 {sha256[:12]}")


def fetch_part(session: str, remote_part: str, local_part: Path, size: int) -> None:
    colab("download", "-s", session, remote_part, str(local_part))
    if local_part.stat().st_size != size:
        raise LaneError(f"{local_part.name}: {local_part.stat().st_size} bytes, the VM has {size}")


def pull(session: str, remote_path: str, size: int, local: Path, sha256: str | None = None,
         parts: list | None = None) -> None:
    """Download a file: in one call, or from the parts the keeper cut beside it on the VM."""
    local.parent.mkdir(parents=True, exist_ok=True)
    if parts:
        work = local.parent / f"{local.name}.parts"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        in_parallel([functools.partial(fetch_part, session, f"{remote_path}.parts/{name}", work / name, part_size)
                     for name, part_size in parts])
        join_parts([work / name for name, _ in parts], local)
        shutil.rmtree(work)
    elif size > PART_BYTES:
        raise LaneError(f"{remote_path} is {size} bytes and was not cut into parts on the VM")
    else:
        colab("download", "-s", session, remote_path, str(local))
    if local.stat().st_size != size:
        raise LaneError(f"{local.name}: got {local.stat().st_size} bytes, the VM has {size}")
    if sha256 and lane.sha256_file(local) != sha256:
        raise LaneError(f"{local.name}: sha256 differs from the box's result.json")


# --- steps ----------------------------------------------------------------------------------------

def submit(stage: Path, slug: str, max_hours: float, dry_run: bool, force: bool) -> None:
    state = lane.load_state(stage)
    previous = state.get("session") if state.get("session") and not state.get("cleaned") else None
    if previous and not force:
        raise LaneError(f"{stage.name} already has a run ({previous}, {state.get('status')}); "
                        "finish/cleanup it, or pass --force")
    intro, narration, outro = lane.preflight(stage, max_hours)
    session = session_name(slug)
    out_dir = stage.parent / f"{stage.name}{BUNDLE_SUFFIX}"
    say(f"packing {stage.name} …")
    bundle, digest = lane.build_bundle(stage, out_dir)
    storyboard = (yaml.safe_load((stage / "job.yaml").read_text(encoding="utf-8")) or {}).get("storyboard") or []
    manifest = {
        "schema": 1, "slug": slug, "session": session,
        "commit": lane.run(["git", "rev-parse", "HEAD"], cwd=lane.REPO), "bundle_sha256": digest,
        "bundle_bytes": bundle.stat().st_size, "narration_seconds": narration,
        "expected_seconds": round(intro + narration + outro, 3), "scenes": len(storyboard),
        "stop_after_s": STOP_AFTER_S,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    say(f"bundle {manifest['bundle_bytes'] / 2**20:.0f} MiB "
        f"({math.ceil(manifest['bundle_bytes'] / PART_BYTES)} parts), {len(storyboard)} scenes, "
        f"narration {narration / 3600:.2f} h, expected video {manifest['expected_seconds']:.2f}s, "
        "credential scan clean")
    if dry_run:
        print(json.dumps({"session": session, "machine": "CPU, high-RAM", "cli_state": str(SESSION_CONFIG),
                          "manifest": manifest}, indent=2))
        say("dry run: no VM created, nothing uploaded")
        return

    balance = parse_balance(colab("usage"))
    if balance is None or balance < MIN_BALANCE_CU:
        raise LaneError(f"compute-unit balance is {balance}, under {MIN_BALANCE_CU} — no VM started")
    if previous:
        say(f"--force: stopping the previous VM {previous} first")
        colab("stop", "-s", previous, check=False)
    say(f"creating {session} (CPU, high-RAM); balance {balance:.2f} CU")
    try:
        colab("new", "-s", session, "--high-mem", timeout=600)
    except BaseException:
        colab("stop", "-s", session, check=False)  # a timed-out `new` may still have allocated it
        raise
    state = {**manifest, "status": "creating", "vm_started_at": time.time(), "balance_before": balance,
             "bundle_dir": str(out_dir)}
    lane.save_state(stage, state)
    try:
        info = parse_session_line(colab("status", "-s", session), session) or {}
        if any(info.get(key) != value for key, value in REQUIRED_SHAPE.items()):
            raise LaneError(f"{session} is not a high-RAM CPU VM: {info or 'no status line'}")
        state["endpoint"] = info["endpoint"]
        lane.save_state(stage, state)
        say(f"{session} ready ({info['endpoint']}), uploading …")
        started = time.time()
        push(session, bundle, f"{REMOTE_IN}/{lane.BUNDLE_NAME}", digest, out_dir / "parts")
        colab("upload", "-s", session, str(out_dir / "manifest.json"), f"{REMOTE_IN}/manifest.json")
        colab("upload", "-s", session, str(lane.BOX_SCRIPT), f"{REMOTE_IN}/{lane.BOX_SCRIPT.name}")
        say(f"uploaded in {time.time() - started:.0f}s, sha256 checked on the VM")
        launched = remote(session, LAUNCH, {"in": REMOTE_IN, "out": REMOTE_OUT,
                                            "box": f"{REMOTE_IN}/{lane.BOX_SCRIPT.name}"})
        state.update(status="running", submitted_at=time.time(), box_pid=launched["pid"])
        lane.save_state(stage, state)
        start_keeper(stage)
    except BaseException:
        say(f"submit failed; stopping {session} so it burns no compute units")
        stop_keeper(lane.load_state(stage))
        colab("stop", "-s", session, check=False)
        lane.save_state(stage, {**lane.load_state(stage), "status": "failed", "cleaned": True})
        raise
    say(f"box started on {session} (pid {launched['pid']}, python {launched['python']}); a keeper cell keeps "
        "the kernel busy, which is what keeps the VM alive")


def watch(stage: Path) -> None:
    state = lane.load_state(stage)
    lane.need(state, "submitted_at", "submit")
    if state.get("status") in ("complete", "partial"):
        say(f"render already {state['status']}")
        return
    if state.get("cleaned"):
        raise LaneError(f"{state['session']} is already stopped ({state.get('status')}) — submit again")
    session = state["session"]
    deadline = state["vm_started_at"] + SESSION_CAP_S
    failures, stale, last_beat, startup_shown = 0, 0, None, False
    next_log = time.time() + LOG_EVERY_S
    while True:
        try:
            status = read_status(stage)
            failures = 0
        except LaneError as exc:
            failures += 1
            say(f"poll failed ({failures}/{MAX_FAILED_POLLS}): {str(exc).splitlines()[0]}")
            if failures >= MAX_FAILED_POLLS:
                if not endpoint_listed(state["endpoint"]):
                    gone(stage)
                raise LaneError(f"{session} did not answer {MAX_FAILED_POLLS} polls in a row but is still "
                                "listed — re-run `watch` once the network is back")
            time.sleep(POLL_S)
            continue
        if status is None or status["beat"] == last_beat:
            stale += 1
            if stale >= STALE_POLLS:
                if not endpoint_listed(state["endpoint"]):
                    gone(stage)
                say(f"status.json has not moved for {stale} polls; starting the keeper cell again")
                start_keeper(stage)
                stale = 0
        else:
            stale, last_beat = 0, status["beat"]
        if status:
            if not startup_shown:
                lines = startup_lines(status["tail"])
                for line in lines or []:
                    say(f"box {line}")
                startup_shown = bool(lines) or any("heartbeat:" in line for line in status["tail"])
            if status["ended"]:
                break
            if time.time() >= next_log:
                beat = lane.latest_box_line("\n".join(status["tail"]))
                if beat:
                    say(f"box {beat}")
                next_log = time.time() + LOG_EVERY_S
        if time.time() > deadline:
            fail_box(stage, f"still rendering past the {SESSION_CAP_S // 3600} h session cap", status or {})
        time.sleep(POLL_S)
    if status["exit"] is None:
        fail_box(stage, "the box process is gone without an exit code", status)
    result = status["result"]
    if status["exit"] != 0 or not result:
        fail_box(stage, f"the box exited {status['exit']}", status)
    state = lane.load_state(stage)
    state.update(status=result["status"], finished_at=time.time())
    lane.save_state(stage, state)
    say(f"render {result['status'].upper()} on Colab after "
        f"{(state['finished_at'] - state['submitted_at']) / 3600:.2f} h")


def gone(stage: Path) -> None:
    """Colab no longer lists the VM: nothing is left on it. Mark the run lost and raise."""
    state = lane.load_state(stage)
    stop_keeper(state)
    lane.save_state(stage, {**state, "status": "lost", "cleaned": True})
    raise LaneError(f"{state['session']} is gone — Colab reclaimed the VM (its kernel went idle, or Colab "
                    "ended the runtime). Nothing is left to fetch: submit again")


def fail_box(stage: Path, why: str, status: dict) -> None:
    """A box failure is final: keep its logs here, stop the VM (nothing else is on it), raise."""
    state = lane.load_state(stage)
    keep = Path(state["bundle_dir"])
    for name in ("box.log", "render.log"):
        if name in status.get("files", {}):
            colab("download", "-s", state["session"], f"{REMOTE_OUT}/{name}", str(keep / name), check=False)
    lane.save_state(stage, {**state, "status": "failed", "finished_at": time.time()})
    try:
        stop_vm(stage)
    except LaneError as exc:
        why += f" — and stopping the VM failed too: {exc}"
    tail = "\n".join(status.get("tail", [])[-40:])
    raise LaneError(f"{why}. Logs kept in {keep}. Last box lines:\n{tail}")


def stop_vm(stage: Path) -> None:
    state = lane.load_state(stage)
    session = state["session"]
    stop_keeper(state)
    out = colab("stop", "-s", session, check=False)
    say(f"stopping {session}: {out.splitlines()[-1] if out else 'ok'}")
    if state.get("endpoint") and endpoint_listed(state["endpoint"]):
        raise LaneError(f"{session} ({state['endpoint']}) is still listed after `colab stop` — stop it by "
                        f"hand: colab --config {SESSION_CONFIG} stop -s {session}")
    balance = parse_balance(colab("usage", check=False))
    state.update(cleaned=True, balance_after=balance)
    lane.save_state(stage, state)
    if balance is not None and state.get("balance_before") is not None:
        say(f"compute units {state['balance_before']:.2f} -> {balance:.2f} (the balance is shared with "
            "every project on this account)")


def fetch(stage: Path) -> None:
    """Download the render, check it, then stop the VM before anything slow happens here."""
    state = lane.load_state(stage)
    lane.need(state, "session", "submit")
    if state.get("fetched"):
        say("fetch already done")
        return
    if state.get("status") not in ("complete", "partial"):
        raise LaneError(f"render status is {state.get('status')!r}, run `watch` until it finishes")
    session, dl = state["session"], stage.parent / f"{stage.name}-dl"
    if not state.get("downloaded"):
        status = read_status(stage)
        if not status or not status["ended"]:
            raise LaneError("the keeper's status.json does not show the box finished — run `watch`")
        files = status["files"]
        if "result.json" not in files:
            raise LaneError(f"no result.json in {REMOTE_OUT}: {sorted(files)}")
        pull(session, f"{REMOTE_OUT}/result.json", files["result.json"], dl / "result.json")
        result = json.loads((dl / "result.json").read_text(encoding="utf-8"))
        if result.get("bundle_sha256") != state["bundle_sha256"]:
            raise LaneError("the VM holds the result of another submission (bundle hash differs)")
        payload = result["clips_tar"] if result.get("status") == "partial" else result["mp4"]
        missing = [name for name in (payload, "job.yaml", "logs.tar") if name not in files]
        if missing:
            raise LaneError(f"the box left no {missing} in {REMOTE_OUT}: {sorted(files)}")
        say(f"downloading {payload} ({files[payload] / 1e9:.2f} GB) …")
        started, parts = time.time(), status.get("parts") or {}
        pull(session, f"{REMOTE_OUT}/{payload}", files[payload], dl / payload, sha256=result["sha256"],
             parts=parts.get(payload))
        for name in ("job.yaml", "logs.tar", "render.log", "box.log"):
            if name in files:
                pull(session, f"{REMOTE_OUT}/{name}", files[name], dl / name, parts=parts.get(name))
        say(f"downloaded in {time.time() - started:.0f}s, sha256 ok")
        state.update(downloaded=True, dl_dir=str(dl), result=result)
        lane.save_state(stage, state)
    if not state.get("cleaned"):
        stop_vm(stage)
        state = lane.load_state(stage)
    result = state["result"]
    if result.get("status") == "partial":
        say(f"the box stopped at its deadline and shipped {result['clips_done']}/{result['scenes']} clips; "
            "finishing the render on this machine …")
        result = lane.complete_locally(stage, dl, result)
        say(f"rendered {result['clips_rendered_locally']} clips + the mux here in "
            f"{result['local_render_seconds'] / 60:.1f} min")
    state.update(fetched=True, result=result)
    lane.save_state(stage, state)
    say(f"fetched {result['mp4']} ({result['bytes'] / 1e9:.2f} GB, render {result['render_seconds'] / 3600:.2f} h "
        f"on {result['cpu_count']} cpu)")


def cleanup(stage: Path, force: bool) -> None:
    """Stop the VM by hand — `fetch` already does it after a good download."""
    state = lane.load_state(stage)
    lane.need(state, "session", "submit")
    if state.get("cleaned"):
        say(f"{state['session']} is already stopped")
        return
    if not state.get("downloaded") and not force:
        raise LaneError("the render is not downloaded yet — stopping the VM loses it (use --force)")
    stop_vm(stage)


def status(stage: Path) -> None:
    state = lane.load_state(stage)
    print(json.dumps({k: v for k, v in state.items() if k != "result"}, indent=2, ensure_ascii=False))
    if state.get("session") and not state.get("cleaned"):
        info = parse_session_line(colab("status", "-s", state["session"], check=False), state["session"])
        say(f"{state['session']}: {info or 'not listed by colab status'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cmd", choices=("run", "submit", "watch", "fetch", "finish", "publish", "purge",
                                        "cleanup", "status"))
    parser.add_argument("stage", type=Path, help="the stage prepared with `videotool prepare --target cloud`")
    parser.add_argument("--slug", help="episode slug (default: the stage folder name)")
    parser.add_argument("--remote", help="rclone path of the episode folder, e.g. gdrive:…/Chap 71")
    parser.add_argument("--max-narration-hours", type=float, default=lane.MAX_NARRATION_H)
    parser.add_argument("--dry-run", action="store_true", help="submit: print the plan, start no VM")
    parser.add_argument("--force", action="store_true", help="submit over an open run / cleanup before fetch")
    args = parser.parse_args(argv)
    stage = args.stage.expanduser().resolve()
    slug = args.slug or stage.name
    try:
        if args.cmd in ("run", "publish") and not args.remote:
            raise LaneError("--remote is required")
        if args.cmd in ("run", "submit"):
            submit(stage, slug, args.max_narration_hours, args.dry_run, args.force)
            if args.dry_run or args.cmd == "submit":
                return 0
        steps = {"watch": [watch], "fetch": [fetch], "finish": [lane.finish], "status": [status],
                 "publish": [lambda s: lane.publish(s, args.remote)], "purge": [lane.purge],
                 "cleanup": [lambda s: cleanup(s, args.force)],
                 "run": [watch, fetch, lane.finish, lambda s: lane.publish(s, args.remote), lane.purge]}
        for step in steps.get(args.cmd, []):
            step(stage)
    except LaneError as exc:
        say(f"FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
