"""Render one episode on the Oracle VPS over ssh — only when the user names the VPS. Runbook:
references/vps-runbook.md.

The Kaggle CPU lane with the VPS as the renderer, shaped like the Colab lane: the episode is prepared and
finished on this machine and the VPS only renders. Nothing secret leaves this machine — the rclone key has
full-Drive scope, so it never goes to the VPS. The box (kaggle_cpu_box.py) runs detached under
~/vtbench/jobs/<slug> with the static ffmpeg and the venv set up under ~/vtbench, so it keeps rendering while
this machine sleeps or the driver is stopped: re-run `watch`. One job at a time: the VPS has two cores, shared
with VieNeu TTS, and the box unpacks every job into the same /tmp/vt.

    .venv/bin/python .agents/skills/make-video/scripts/vps_render.py run STAGE --remote "gdrive:…/Chap NN"

Steps, each re-runnable (state in STAGE/.vps.json): submit [--dry-run], watch, fetch, finish,
publish --remote, purge, cleanup [--force], status. Run with the repo venv (PyYAML).

No narration cap and no safety-net stop (user 2026-10-21): the VPS has no session wall, and the safety net
would hand unfinished clips to this machine to render.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml


def _own_lane():
    """A private copy of kaggle_cpu_render (preflight, bundle, finish, verify, publish, purge): the shared
    steps read their state file and log tag from module globals, and colab_render sets its own on the
    imported module."""
    spec = importlib.util.spec_from_file_location("vps_lane", Path(__file__).with_name("kaggle_cpu_render.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STATE_NAME, module.TAG = ".vps.json", "vps"
    return module


lane = _own_lane()
LaneError, say = lane.LaneError, lane.say

HOST = os.environ.get("VT_VPS_HOST", "oracle-vps")  # the ~/.ssh/config alias of the Oracle VPS
BASE = "vtbench"  # under the VPS user's home: ff/bin (static ffmpeg), py (venv), jobs/
FFMPEG_BIN = f"{BASE}/ff/bin"
PYTHON = f"{BASE}/py/bin/python"
JOBS = f"{BASE}/jobs"
LOCK = f"{JOBS}/.lock"  # holds the slug of the one job allowed at a time
BOX_SCRATCH = "/tmp/vt"  # kaggle_cpu_box unpacks every job here and never clears it first
BUNDLE_SUFFIX = "-vps"  # STAGE-vps/ holds bundle + manifest (+ box logs of a failed run)
MAX_LOAD = 1.5  # two cores: above this something else is running (VieNeu TTS?)
MIN_FREE_GB = 20.0  # bundle + job dir (6.7 GB for 2.3 h on Colab, 2026-10-21) + mp4 + margin
POLL_S = 300
MAX_FAILED_POLLS = 6
SSH_TIMEOUT_S = 120
COPY_TIMEOUT_S = 3600
# One ssh stream VPS → here is capped, so the render comes down in pieces over several connections at once.
# 1 GiB test, 2026-10-22, while the VPS rendered: 1 stream 2.4 MiB/s, 4 streams 15.9 MiB/s, 8 streams 12.2 MiB/s.
PIECE_BYTES = 128 * 2**20
DOWNLOAD_STREAMS = 4
PIECE_ATTEMPTS = 3
PIECE_TIMEOUT_S = 900
RETRY_PAUSE_S = 5

# --- snippets run with the VPS's python3, from the user's home (argv: see each call) --------------

READY = """
import json, os, shutil, sys
jobs, lock, ffmpeg, python = sys.argv[1:5]
os.makedirs(jobs, exist_ok=True)
holder = open(lock).read().strip() if os.path.isfile(lock) else None
print(json.dumps({"load1": os.getloadavg()[0], "free_gb": shutil.disk_usage(jobs).free / 1e9, "holder": holder,
                  "ffmpeg": os.access(ffmpeg, os.X_OK), "python": os.access(python, os.X_OK)}))
"""

TAKE = """
import json, os, sys
lock, slug = sys.argv[1:3]
try:
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
except FileExistsError:
    print(json.dumps({"taken": False, "holder": open(lock).read().strip()}))
else:
    os.write(fd, slug.encode())
    os.close(fd)
    print(json.dumps({"taken": True, "holder": slug}))
"""

# The box runs detached in its own session with every fd closed, so ssh returns at once and the render
# outlives this connection; bash writes box.exit when the box ends, whatever the reason.
LAUNCH = """
import json, os, shlex, shutil, subprocess, sys
job, python, ffbin, box, scratch = sys.argv[1:6]
job, python, ffbin = os.path.abspath(job), os.path.abspath(python), os.path.abspath(ffbin)
work = os.path.join(job, "work")
os.makedirs(work, exist_ok=True)
for name in ("box.exit", "box.pid", "box.log", "result.json"):
    if os.path.exists(os.path.join(work, name)):
        os.remove(os.path.join(work, name))
shutil.rmtree(scratch, ignore_errors=True)
env = {**os.environ, "VT_BOX_INPUT": os.path.join(job, "in"), "VT_BOX_WORK": work, "PYTHONUNBUFFERED": "1",
       "PATH": ffbin + os.pathsep + os.environ.get("PATH", "")}
q = shlex.quote
cmd = (f"{q(python)} {q(os.path.join(job, 'in', box))} > {q(work + '/box.log')} 2>&1; "
       f"echo $? > {q(work + '/box.exit')}")
proc = subprocess.Popen(["bash", "-c", cmd], env=env, cwd=work, start_new_session=True,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
with open(os.path.join(work, "box.pid"), "w") as fh:
    fh.write(str(proc.pid))
print(json.dumps({"pid": proc.pid}))
"""

PROBE = """
import json, os, sys
work = sys.argv[1]
def read(name):
    path = os.path.join(work, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()
def alive(pid):
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, ValueError, IndexError):
        return False
code, pid, result = (read("box.exit") or "").strip(), (read("box.pid") or "").strip(), read("result.json")
files = ({n: os.path.getsize(os.path.join(work, n)) for n in sorted(os.listdir(work))
          if os.path.isfile(os.path.join(work, n))} if os.path.isdir(work) else {})
print(json.dumps({"exit": int(code) if code.lstrip("-").isdigit() else None,
                  "alive": pid.isdigit() and alive(int(pid)),
                  "tail": (read("box.log") or "").splitlines()[-40:], "files": files,
                  "result": json.loads(result) if result else None}))
"""

# Frees the VPS: optionally stops the box's process group, deletes the job folder, and — only while this
# job holds the lock — the box's scratch folder and the lock itself.
CLEAN = """
import json, os, shutil, signal, sys
job, lock, slug, scratch, kill = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] == "1"
killed = None
pid_file = os.path.join(job, "work", "box.pid")
if kill and os.path.isfile(pid_file):
    pid = int(open(pid_file).read().strip())
    try:
        os.killpg(pid, signal.SIGTERM)
        killed = pid
    except ProcessLookupError:
        pass
holder = open(lock).read().strip() if os.path.isfile(lock) else None
if holder == slug:
    shutil.rmtree(scratch, ignore_errors=True)
    os.remove(lock)
shutil.rmtree(job, ignore_errors=True)
print(json.dumps({"killed": killed, "released": holder == slug, "holder": holder}))
"""

# Writes bytes [offset, offset + length) of a file to stdout: one piece of a download.
RANGE = """
import sys
path, offset, length = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
out = sys.stdout.buffer
with open(path, "rb") as src:
    src.seek(offset)
    while length > 0:
        chunk = src.read(min(length, 1 << 20))
        if not chunk:
            break
        out.write(chunk)
        length -= len(chunk)
out.flush()
"""


# --- pure helpers ---------------------------------------------------------------------------------

def job_dir(slug: str) -> str:
    safe = lane.slugify(slug)
    if not safe:
        raise LaneError(f"slug {slug!r} has nothing left after slugify")
    return f"{JOBS}/{safe}"


def check_ready(info: dict, slug: str, force: bool) -> None:
    """Refuse a submit the VPS cannot take now: tools missing, another job holding it, busy, or full."""
    problems = []
    if not (info["ffmpeg"] and info["python"]):
        problems.append(f"no {FFMPEG_BIN}/ffmpeg or {PYTHON} on the VPS — set it up per references/vps-runbook.md")
    holder = info.get("holder")
    if holder and holder != lane.slugify(slug):
        problems.append(f"{holder} holds the VPS — one render at a time: finish or `cleanup --force` it first")
    elif holder and not force:
        problems.append(f"{holder} already has a job on the VPS — finish/cleanup it, or pass --force")
    if info["load1"] > MAX_LOAD and not force:
        problems.append(f"the VPS is busy (load {info['load1']:.1f} on 2 cores; VieNeu TTS?) — wait, or pass --force")
    if info["free_gb"] < MIN_FREE_GB:
        problems.append(f"only {info['free_gb']:.0f} GB free on the VPS, a render needs {MIN_FREE_GB:.0f}")
    if problems:
        raise LaneError("; ".join(problems))


def parse_json_line(output: str) -> dict:
    """The JSON object a snippet printed on its last line."""
    try:
        return json.loads(output.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise LaneError(f"the VPS did not answer with JSON:\n{output[-1500:]}") from exc


# --- ssh / scp ------------------------------------------------------------------------------------

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]


def ssh_argv(*argv: str) -> list[str]:
    """The ssh call running one command on the VPS, each argument quoted for its shell. -n gives it no
    stdin, so a detached child cannot hold the connection open."""
    return ["ssh", "-n", *SSH_OPTS, HOST, " ".join(shlex.quote(arg) for arg in argv)]


def ssh(*argv: str, timeout: float = SSH_TIMEOUT_S) -> str:
    """One command on the VPS; returns what it printed."""
    try:
        proc = subprocess.run(ssh_argv(*argv), capture_output=True, text=True,
                              errors="replace", stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LaneError(f"ssh {HOST} {argv[0]} … gave no answer in {timeout:.0f}s") from exc
    if proc.returncode != 0:
        raise LaneError(f"ssh {HOST} {argv[0]} … failed (exit {proc.returncode}): "
                        f"{(proc.stdout + proc.stderr).strip()[-1500:]}")
    return proc.stdout


def snippet(code: str, *args: str, timeout: float = SSH_TIMEOUT_S) -> dict:
    return parse_json_line(ssh("python3", "-c", code, *args, timeout=timeout))


def scp(sources: list[str], dest: str, timeout: float = COPY_TIMEOUT_S) -> None:
    try:
        proc = subprocess.run(["scp", "-q", *SSH_OPTS, *sources, dest], capture_output=True, text=True,
                              errors="replace", stdin=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LaneError(f"scp to {dest} took over {timeout:.0f}s") from exc
    if proc.returncode != 0:
        raise LaneError(f"scp to {dest} failed (exit {proc.returncode}): {(proc.stdout + proc.stderr).strip()[-1500:]}")


def copy_to(local: list[Path], remote_dir: str) -> None:
    scp([str(p) for p in local], f"{HOST}:{remote_dir}/")


def copy_from(remote_path: str, local: Path, size: int | None = None) -> None:
    """One file from the VPS; a file bigger than a piece (size given) comes down with `download`."""
    local.parent.mkdir(parents=True, exist_ok=True)
    if size is not None and size > PIECE_BYTES:
        download(remote_path, local, size)
    else:
        scp([f"{HOST}:{remote_path}"], str(local))


def download(remote_path: str, local: Path, size: int) -> None:
    """A big file in PIECE_BYTES pieces, DOWNLOAD_STREAMS at a time over their own ssh connections, each
    written in place and tried PIECE_ATTEMPTS times; the first piece that fails every try cancels the ones
    not started and raises. The caller checks the sha256 of the whole file."""
    with open(local, "wb") as fh:
        fh.truncate(size)

    def attempt(offset: int) -> None:
        for n in range(1, PIECE_ATTEMPTS + 1):
            try:
                fetch_piece(remote_path, local, offset, min(PIECE_BYTES, size - offset))
                return
            except LaneError:
                if n == PIECE_ATTEMPTS:
                    raise
                time.sleep(RETRY_PAUSE_S * n)

    pool = ThreadPoolExecutor(DOWNLOAD_STREAMS)
    try:
        for future in as_completed([pool.submit(attempt, offset) for offset in range(0, size, PIECE_BYTES)]):
            future.result()
    finally:
        pool.shutdown(cancel_futures=True)


def fetch_piece(remote_path: str, local: Path, offset: int, length: int) -> None:
    """Bytes [offset, offset + length) of a VPS file, written at the same place in `local`: ssh writes
    straight into the file through a descriptor positioned at `offset`."""
    fd = os.open(local, os.O_WRONLY)
    try:
        os.lseek(fd, offset, os.SEEK_SET)
        try:
            proc = subprocess.run(ssh_argv("python3", "-c", RANGE, remote_path, str(offset), str(length)),
                                  stdout=fd, stderr=subprocess.PIPE, text=True, errors="replace",
                                  stdin=subprocess.DEVNULL, timeout=PIECE_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise LaneError(f"bytes {offset}+{length} of {remote_path} took over {PIECE_TIMEOUT_S}s") from exc
        got = os.lseek(fd, 0, os.SEEK_CUR) - offset
    finally:
        os.close(fd)
    if proc.returncode != 0 or got != length:
        raise LaneError(f"bytes {offset}+{length} of {remote_path}: got {got} (exit {proc.returncode}) "
                        f"{proc.stderr.strip()[-500:]}")


def probe(state: dict) -> dict:
    return snippet(PROBE, f"{state['job_dir']}/work")


def free_vps(state: dict, kill: bool = False) -> dict:
    return snippet(CLEAN, state["job_dir"], LOCK, lane.slugify(state["slug"]), BOX_SCRATCH, "1" if kill else "0")


# --- steps ----------------------------------------------------------------------------------------

def submit(stage: Path, slug: str, max_hours: float, dry_run: bool, force: bool) -> None:
    state = lane.load_state(stage)
    if state.get("submitted_at") and not state.get("cleaned") and not force:
        raise LaneError(f"{stage.name} already has a run on the VPS ({state.get('status')}); "
                        "finish/cleanup it, or pass --force")
    intro, narration, outro = lane.preflight(stage, max_hours)
    job = job_dir(slug)
    info = snippet(READY, JOBS, LOCK, f"{FFMPEG_BIN}/ffmpeg", PYTHON)
    out_dir = stage.parent / f"{stage.name}{BUNDLE_SUFFIX}"
    say(f"packing {stage.name} …")
    bundle, digest = lane.build_bundle(stage, out_dir)
    storyboard = (yaml.safe_load((stage / "job.yaml").read_text(encoding="utf-8")) or {}).get("storyboard") or []
    manifest = {
        "schema": 1, "slug": slug, "host": HOST,
        "commit": lane.run(["git", "rev-parse", "HEAD"], cwd=lane.REPO), "bundle_sha256": digest,
        "bundle_bytes": bundle.stat().st_size, "narration_seconds": narration,
        "expected_seconds": round(intro + narration + outro, 3), "scenes": len(storyboard),
        "stop_after_s": None,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    say(f"bundle {manifest['bundle_bytes'] / 2**20:.0f} MiB, {len(storyboard)} scenes, narration "
        f"{narration / 3600:.2f} h, expected video {manifest['expected_seconds']:.2f}s, credential scan clean; "
        f"VPS load {info['load1']:.2f}, {info['free_gb']:.0f} GB free, lock {info['holder'] or 'free'}")
    check_ready(info, slug, force)
    if dry_run:
        print(json.dumps({"host": HOST, "job_dir": job, "manifest": manifest}, indent=2))
        say("dry run: nothing uploaded, nothing started")
        return
    safe = lane.slugify(slug)
    if info["holder"] == safe:  # --force over this episode's own earlier job: stop it, free the VPS
        say(f"--force: stopping the earlier {safe} job on the VPS")
        snippet(CLEAN, job, LOCK, safe, BOX_SCRATCH, "1")
    taken = snippet(TAKE, LOCK, safe)
    if not taken["taken"]:
        raise LaneError(f"{taken['holder']} took the VPS in the meantime — one render at a time")
    state = {**manifest, "status": "uploading", "job_dir": job, "bundle_dir": str(out_dir)}
    lane.save_state(stage, state)
    try:
        ssh("mkdir", "-p", f"{job}/in", f"{job}/work")
        say(f"uploading to {HOST}:{job} …")
        started = time.time()
        copy_to([bundle, out_dir / "manifest.json", lane.BOX_SCRIPT], f"{job}/in")
        say(f"uploaded in {time.time() - started:.0f}s")
        launched = snippet(LAUNCH, job, PYTHON, FFMPEG_BIN, lane.BOX_SCRIPT.name, BOX_SCRATCH)
    except BaseException:
        say("submit failed; freeing the VPS")
        try:
            free_vps(state, kill=True)
        except LaneError as exc:
            say(f"freeing the VPS failed too: {exc} — run `cleanup --force`")
        lane.save_state(stage, {**state, "status": "failed", "cleaned": True})
        raise
    state.update(status="running", submitted_at=time.time(), box_pid=launched["pid"])
    lane.save_state(stage, state)
    say(f"box started on {HOST} (pid {launched['pid']}); it keeps rendering if this machine sleeps or the "
        "driver stops — re-run `watch`")


def watch(stage: Path) -> None:
    state = lane.load_state(stage)
    lane.need(state, "submitted_at", "submit")
    if state.get("status") == "complete":
        say("render already complete")
        return
    if state.get("cleaned"):
        raise LaneError(f"the VPS job is already gone ({state.get('status')}) — submit again")
    failures, startup_shown, last_beat = 0, False, None
    while True:
        try:
            status = probe(state)
            failures = 0
        except LaneError as exc:
            failures += 1
            say(f"poll failed ({failures}/{MAX_FAILED_POLLS}): {str(exc).splitlines()[0]}")
            if failures >= MAX_FAILED_POLLS:
                raise LaneError(f"the VPS did not answer {MAX_FAILED_POLLS} polls in a row; the box keeps "
                                "rendering there — re-run `watch` once the network is back")
            time.sleep(POLL_S)
            continue
        if not startup_shown:
            lines = lane.startup_lines(status["tail"])
            for line in lines or []:
                say(f"box {line}")
            startup_shown = bool(lines) or any("heartbeat:" in line for line in status["tail"])
        beat = lane.latest_box_line("\n".join(status["tail"]))
        if startup_shown and "heartbeat:" in beat and beat != last_beat:
            say(f"box {beat}")
            last_beat = beat
        if status["exit"] is not None or not status["alive"]:
            break
        time.sleep(POLL_S)
    if status["exit"] is None:  # the box may have exited between the two reads: look once more
        time.sleep(5)
        status = probe(state)
        if status["exit"] is None:
            fail_box(stage, "the box process is gone without an exit code", status)
    result = status["result"]
    if status["exit"] != 0 or not result or result.get("status") != "complete":
        fail_box(stage, f"the box exited {status['exit']}", status)
    state = lane.load_state(stage)
    state.update(status="complete", finished_at=time.time())
    lane.save_state(stage, state)
    say(f"render COMPLETE on the VPS after {(state['finished_at'] - state['submitted_at']) / 3600:.2f} h")


def fail_box(stage: Path, why: str, status: dict) -> None:
    """A box failure is final: keep its logs here, free the VPS (nothing else of this job is there), raise."""
    state = lane.load_state(stage)
    keep = Path(state["bundle_dir"])
    for name in ("box.log", "render.log"):
        if name in status.get("files", {}):
            try:
                copy_from(f"{state['job_dir']}/work/{name}", keep / name)
            except LaneError:
                pass
    try:
        free_vps(state, kill=True)
    except LaneError as exc:
        why += f" — and freeing the VPS failed too ({exc}); run `cleanup --force`"
    lane.save_state(stage, {**state, "status": "failed", "finished_at": time.time(), "cleaned": True})
    tail = "\n".join(status.get("tail", [])[-40:])
    raise LaneError(f"{why}. Logs kept in {keep}. Last box lines:\n{tail}")


def fetch(stage: Path) -> None:
    """Download the render, check it against the box's result.json, then free the VPS."""
    state = lane.load_state(stage)
    lane.need(state, "submitted_at", "submit")
    if state.get("fetched"):
        say("fetch already done")
        return
    if state.get("status") != "complete":
        raise LaneError(f"render status is {state.get('status')!r}, run `watch` until it finishes")
    dl = stage.parent / f"{stage.name}-dl"
    if not state.get("downloaded"):
        status = probe(state)
        result, files = status["result"], status["files"]
        if not result or result.get("bundle_sha256") != state["bundle_sha256"]:
            raise LaneError("the VPS job holds no result of this submission (bundle hash differs or missing)")
        missing = [name for name in (result["mp4"], "job.yaml", "logs.tar") if name not in files]
        if missing:
            raise LaneError(f"the box left no {missing} in {state['job_dir']}/work: {sorted(files)}")
        size = files[result["mp4"]]
        say(f"downloading {result['mp4']} ({size / 1e9:.2f} GB, {DOWNLOAD_STREAMS} streams) …")
        started = time.time()
        copy_from(f"{state['job_dir']}/work/{result['mp4']}", dl / result["mp4"], size)
        took = time.time() - started
        if lane.sha256_file(dl / result["mp4"]) != result["sha256"]:
            raise LaneError(f"{result['mp4']}: sha256 differs from the box's result.json")
        for name in ("job.yaml", "logs.tar", "render.log", "box.log", "result.json"):
            if name in files:
                copy_from(f"{state['job_dir']}/work/{name}", dl / name)
        say(f"downloaded in {took:.0f}s ({size / 1e6 / max(took, 1):.1f} MB/s), sha256 ok")
        state.update(downloaded=True, dl_dir=str(dl), result=result)
        lane.save_state(stage, state)
    if not state.get("cleaned"):
        freed = free_vps(state)
        say(f"freed the VPS: {state['job_dir']} deleted"
            + (f", {BOX_SCRATCH} deleted and the lock released" if freed["released"] else ""))
        state.update(cleaned=True)
        lane.save_state(stage, state)
    result = state["result"]
    state.update(fetched=True)
    lane.save_state(stage, state)
    say(f"fetched {result['mp4']} ({result['bytes'] / 1e9:.2f} GB, render {result['render_seconds'] / 3600:.2f} h "
        f"on {result['cpu_count']} cpu)")


def cleanup(stage: Path, force: bool) -> None:
    """Free the VPS by hand — `fetch` already does it after a good download."""
    state = lane.load_state(stage)
    lane.need(state, "job_dir", "submit")
    if state.get("cleaned"):
        say("the VPS job is already gone")
        return
    if not state.get("downloaded") and not force:
        raise LaneError("the render is not downloaded yet — cleanup deletes it on the VPS and stops a running "
                        "box (use --force)")
    freed = free_vps(state, kill=True)
    say(f"freed the VPS ({'stopped box pid ' + str(freed['killed']) if freed['killed'] else 'no box stopped'})")
    state.update(cleaned=True, status=state.get("status") if state.get("downloaded") else "cancelled")
    lane.save_state(stage, state)


def status(stage: Path) -> None:
    state = lane.load_state(stage)
    print(json.dumps({k: v for k, v in state.items() if k != "result"}, indent=2, ensure_ascii=False))
    if state.get("job_dir") and not state.get("cleaned"):
        now = probe(state)
        say(f"box exit {now['exit']}, running {now['alive']}: {lane.latest_box_line(chr(10).join(now['tail']))}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cmd", choices=("run", "submit", "watch", "fetch", "finish", "publish", "purge",
                                        "cleanup", "status"))
    parser.add_argument("stage", type=Path, help="the stage prepared with `videotool prepare --target cloud`")
    parser.add_argument("--slug", help="episode slug (default: the stage folder name)")
    parser.add_argument("--remote", help="rclone path of the episode folder, e.g. gdrive:…/Chap 82")
    parser.add_argument("--max-narration-hours", type=float, default=math.inf,
                        help="no cap by default on the VPS (user 2026-10-21)")
    parser.add_argument("--dry-run", action="store_true", help="submit: print the plan, upload nothing")
    parser.add_argument("--force", action="store_true",
                        help="submit over this episode's open job or a busy VPS / cleanup before fetch")
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
