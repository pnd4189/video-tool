"""Render one episode on a Kaggle CPU-only kernel from the CLI, no browser. Runbook:
references/kaggle-cpu-runbook.md.

The Modal shape with Kaggle as the renderer: the episode is prepared and finished on this machine and
Kaggle only renders. Nothing secret leaves this machine — the rclone key has full-Drive scope, so it
never goes to Kaggle. Each episode gets its own private dataset (bundle.vtb + manifest.json) and its
own private CPU script kernel `<owner>/videotool-cpu-<slug>-<hash>`, both deleted after a verified
publish. The frozen GPU/TPU kernels are never pushed.

    .venv/bin/python .agents/skills/make-video/scripts/kaggle_cpu_render.py run STAGE --remote "gdrive:…/Chap NN"

Steps, each re-runnable (state in STAGE/.kaggle-cpu.json): submit [--dry-run], watch, fetch, finish,
publish --remote, cleanup [--force], purge, status. `run` ends with purge: the local stage and its
-dl/-kcpu siblings are deleted once the episode is on Drive. Run with the repo venv (PyYAML).

colab_render.py (the Colab CLI lane) imports this module for the backend-neutral steps (preflight,
bundle, finish, verify, publish, purge) under its own state file and log tag.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
BOX_SCRIPT = Path(__file__).with_name("kaggle_cpu_box.py")
BOX_REL = BOX_SCRIPT.relative_to(REPO).as_posix()
PURGE_SCRIPT = Path(__file__).with_name("purge_stage.py")
VT = REPO / ".venv/bin/videotool"
KERNEL_PREFIX = "videotool-cpu-"
DATASET_PREFIX = "videotool-cpu-job-"
FROZEN_KERNELS = ("videotool-render", "videotool-render-tpu")  # GPU/TPU lanes: never pushed from here
MAX_SLUG_LEN = 50
HASH_LEN = 6
CODE_PATHS = ("src", "Colab", "pyproject.toml", "README.md")
BUNDLE_NAME = "bundle.vtb"  # an uncompressed tar; a neutral suffix so Kaggle never unpacks it on upload
STATE_NAME = ".kaggle-cpu.json"
TAG = "kcpu"  # log tag; colab_render.py sets its own TAG and STATE_NAME on its import of this module
KERNEL_TIMEOUT_S = 41_400  # 11.5 h, under Kaggle's 12 h session cap
# The box stops this long before the timeout and ships its finished clips; this machine finishes the
# render. Room for the tar (~4 GB, minutes) and for Kaggle to save the output after the script exits.
STOP_MARGIN_S = 45 * 60
# User decision 2026-10-12. With overlays baked per clip + x264 `faster` the box needs ~1.9 h per
# video-hour (Chap 71 trial + bench, 2026-10-13), so 3.5 h of narration projects to ~6.8 h.
MAX_NARRATION_H = 3.5
CLIPS_TAR = "clips.tar"
POLL_S = 60
DATASET_POLL_S = 15
DATASET_READY_TIMEOUT_S = 45 * 60
MAX_UNKNOWN_POLLS = 5
LOG_EVERY_S = 600
SIZE_CAP_BYTES = 4_500_000_000  # the user's published-file ceiling
DURATION_TOLERANCE_S = 0.3
VIDEO_AUDIO_SLACK_S = 1.0  # Modal Chap 67 measured the video ~0.4 s longer; harmless, subtitles follow audio
CREDENTIAL_NAMES = {"rclone.conf", "kaggle.json", "access_token", ".env", "credentials.json", "token.json"}
CREDENTIAL_GLOBS = ("client_secret*.json", "*.pem", "*.p12", "id_rsa*", "id_ed25519*")
CREDENTIAL_MARKERS = (b"refresh_token", b"client_secret", b"PRIVATE KEY")
TEXT_SCAN_MAX_BYTES = 1 << 20


class LaneError(RuntimeError):
    """A refused or failed step; the message is what the user needs to act on."""


def say(msg: str) -> None:
    print(f"[{TAG} {dt.datetime.now():%H:%M}] {msg}", flush=True)


# --- pure helpers ---------------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def ids_for(owner: str, slug: str, digest: str) -> tuple[str, str]:
    """(kernel_id, dataset_id): one pair per bundle, ≤ 50-char names, fixed prefixes."""
    def name(prefix: str) -> str:
        room = MAX_SLUG_LEN - len(prefix) - HASH_LEN - 1
        return f"{prefix}{slugify(slug)[:room].rstrip('-')}-{digest[:HASH_LEN]}"
    return f"{owner}/{name(KERNEL_PREFIX)}", f"{owner}/{name(DATASET_PREFIX)}"


def assert_safe_kernel_ref(ref: str, owner: str) -> str:
    kernel_owner, _, name = ref.partition("/")
    if kernel_owner != owner or name in FROZEN_KERNELS or not name.startswith(KERNEL_PREFIX):
        raise LaneError(f"refusing to touch kernel {ref!r}: this lane only owns {owner}/{KERNEL_PREFIX}*")
    return ref


def kernel_metadata(kernel_id: str, dataset_id: str) -> dict:
    return {
        "id": kernel_id, "title": kernel_id.split("/", 1)[1], "code_file": BOX_SCRIPT.name,
        "language": "python", "kernel_type": "script", "is_private": "true",
        "enable_gpu": "false", "enable_tpu": "false", "enable_internet": "true",
        "dataset_sources": [dataset_id], "competition_sources": [], "kernel_sources": [],
        "model_sources": [],
    }


def dataset_metadata(dataset_id: str) -> dict:
    # License "unknown" is what TTS_Local's private model dataset uses and it mounts fine.
    return {"title": dataset_id.split("/", 1)[1], "id": dataset_id, "licenses": [{"name": "unknown"}]}


def scan_credentials(root: Path) -> list[str]:
    """Paths under root that look like a credential (by name, or a small file containing a marker)."""
    hits = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if path.name in CREDENTIAL_NAMES or any(fnmatch.fnmatch(path.name, g) for g in CREDENTIAL_GLOBS):
            hits.append(rel)
        elif path.stat().st_size <= TEXT_SCAN_MAX_BYTES:
            data = path.read_bytes()
            if any(marker in data for marker in CREDENTIAL_MARKERS):
                hits.append(rel)
    return hits


def _srt_seconds(stamp: str) -> float:
    h, m, s = stamp.strip().replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def srt_cue_bounds(text: str) -> tuple[float, float]:
    """(first cue start, last cue end) in seconds."""
    stamps = re.findall(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)", text)
    if not stamps:
        raise LaneError("no SRT cues found")
    return _srt_seconds(stamps[0][0]), _srt_seconds(stamps[-1][1])


def check_narration(seconds: float, max_hours: float) -> None:
    if seconds > max_hours * 3600:
        raise LaneError(f"narration {seconds / 3600:.2f} h exceeds this lane's {max_hours} h cap "
                        "— render it on Modal or locally")


def parse_status(cli_output: str) -> str:
    """'x has status "KernelWorkerStatus.COMPLETE"' -> 'complete'."""
    m = re.search(r'has status "([^"]+)"', cli_output)
    return m.group(1).split(".")[-1].lower() if m else "unknown"


def is_terminal(status: str) -> bool:
    return status in ("complete", "error") or status.startswith("cancel")


def cli_error(output: str) -> bool:
    """Dataset create/version print their failure and still exit 0 (kaggle CLI 2.x)."""
    return "error" in output.lower()


def parse_dataset_files(listing: str) -> dict[str, int]:
    """`kaggle datasets files` table -> {name: size}; an error message parses to {}."""
    files = {}
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            files[parts[0]] = int(parts[1])
    return files


def dataset_has_files(listing: str, expected: dict[str, int | None]) -> bool:
    """Every expected file is listed, with the expected size where one is given."""
    files = parse_dataset_files(listing)
    return all(name in files and (size is None or files[name] == size) for name, size in expected.items())


def bundle_excluded(rel: str) -> bool:
    return (rel == STATE_NAME or rel.startswith(".videotool/tmp/")
            or (rel.startswith("outputs/") and rel.endswith(".mp4")))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- subprocess wrappers --------------------------------------------------------------------------

def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace")
    out = (proc.stdout + proc.stderr).strip()
    if check and proc.returncode != 0:
        raise LaneError(f"{' '.join(cmd[:4])} … failed (exit {proc.returncode}):\n{out[-2000:]}")
    return out


def kaggle_exe() -> str:
    exe = shutil.which("kaggle") or str(Path.home() / ".local/bin/kaggle")
    if not Path(exe).exists():
        raise LaneError("`kaggle` CLI not found — install it and run `kaggle auth login`")
    return exe


def kaggle(*args: str, check: bool = True) -> str:
    return run([kaggle_exe(), *args], check=check)


def box_log_so_far(kernel_id: str, seconds: float = 20) -> str:
    """The kernel's log up to now. Plain `kaggle kernels logs` stays empty until the run ends (Chap 71,
    2026-10-12); `-f` replays the log from the start and then follows, so stop it after a moment."""
    proc = subprocess.Popen([kaggle_exe(), "kernels", "logs", "-f", kernel_id], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")
    try:
        out, _ = proc.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return log_text(out or "")


def log_text(raw: str) -> str:
    """A finished kernel's log comes back as a JSON array of `{"stream_name", "time", "data"}` lines
    (Chap 71's failure tail was unreadable for it); a running one streams plain text. Plain text either way."""
    out = []
    for line in raw.splitlines():
        if line.strip() in ("[", "]"):
            continue
        item = line.strip().lstrip("[,").rstrip("]").strip()
        if item.startswith("{") and '"data"' in item:
            try:
                out.append(str(json.loads(item).get("data", "")))
                continue
            except ValueError:
                pass
        out.append(line + "\n")
    return "".join(out)


def kaggle_owner() -> str:
    m = re.search(r"username:\s*(\S+)", kaggle("config", "view"))
    if not m or m.group(1) == "None":
        raise LaneError("Kaggle username not configured — run `kaggle auth login`")
    return m.group(1)


def code_parity_problems(repo: Path, committed: tuple[str, ...] = (*CODE_PATHS, BOX_REL)) -> list[str]:
    """Why the box would not run the code the other lanes run (empty = fine): everything shipped must
    be committed, and the videotool code must equal origin/main, which the GPU/TPU boxes install."""
    problems = []
    dirty = run(["git", "status", "--porcelain", "--", *committed], cwd=repo)
    if dirty:
        problems.append(f"uncommitted changes in shipped code:\n{dirty}")
    diff = subprocess.run(["git", "diff", "--quiet", "origin/main", "HEAD", "--", *CODE_PATHS],
                          cwd=repo, capture_output=True)
    if diff.returncode != 0:
        problems.append("src/ Colab/ pyproject.toml README.md differ from origin/main (or origin/main is "
                        "missing) — this lane would render with code the GPU/TPU lanes do not run")
    return problems


def media_seconds(path: Path, stream: str | None = None) -> float:
    """Container duration, or one stream's (`stream="a:0"`) — the final mp4's video can run ~0.4 s past
    its audio from per-clip frame rounding (modal-runbook gotchas), so sync checks use the audio."""
    entries = ["-select_streams", stream, "-show_entries", "stream=duration"] if stream \
        else ["-show_entries", "format=duration"]
    return float(run(["ffprobe", "-v", "error", *entries, "-of", "default=nw=1:nk=1", str(path)]))


def expected_seconds(stage: Path) -> tuple[float, float, float]:
    """(intro CTA, narration, outro CTA) from the media the job points at."""
    inputs = (yaml.safe_load((stage / "job.yaml").read_text(encoding="utf-8")) or {}).get("inputs") or {}
    def dur(key: str) -> float:
        return media_seconds(stage / inputs[key]) if inputs.get(key) else 0.0
    return dur("intro_cta"), dur("voice"), dur("outro_cta")


# --- state ----------------------------------------------------------------------------------------

def load_state(stage: Path) -> dict:
    path = stage / STATE_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(stage: Path, state: dict) -> None:
    (stage / STATE_NAME).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def need(state: dict, key: str, step: str) -> None:
    if not state.get(key):
        raise LaneError(f"run `{step}` first (state has no {key!r})")


# --- steps ----------------------------------------------------------------------------------------

def build_bundle(stage: Path, out_dir: Path, repo: Path = REPO) -> tuple[Path, str]:
    """The bundle = repo/ (committed code at HEAD) + job/ (the prepared stage), one uncompressed tar."""
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle = out_dir / BUNDLE_NAME
    run(["git", "archive", "--format=tar", "--prefix=repo/", "-o", str(bundle), "HEAD", "--", *CODE_PATHS],
        cwd=repo)
    with tarfile.open(bundle, "a") as tar:
        for path in sorted(p for p in stage.rglob("*") if p.is_file()):
            rel = path.relative_to(stage).as_posix()
            if not bundle_excluded(rel):
                tar.add(path, arcname=f"job/{rel}")
    return bundle, sha256_file(bundle)


def preflight(stage: Path, max_hours: float) -> tuple[float, float, float]:
    """The checks before anything leaves this machine: a validated job, the code the other lanes run,
    narration under the cap, no credentials. Returns (intro CTA, narration, outro CTA) seconds."""
    if not (stage / "job.yaml").exists():
        raise LaneError(f"{stage}/job.yaml missing — run `videotool prepare {stage} --target cloud …` first")
    run([str(VT), "validate", str(stage / "job.yaml")])
    if subprocess.run(["git", "fetch", "-q", "origin"], cwd=REPO).returncode != 0:
        say("warning: git fetch failed, comparing with the last fetched origin/main")
    problems = code_parity_problems(REPO)
    if problems:
        raise LaneError("code check failed:\n- " + "\n- ".join(problems))
    _, narration_end = srt_cue_bounds((stage / "outputs/captions.srt").read_text(encoding="utf-8"))
    check_narration(narration_end, max_hours)
    hits = scan_credentials(stage)
    if hits:
        raise LaneError(f"possible credentials in the stage, refusing to upload: {hits}")
    return expected_seconds(stage)


def submit(stage: Path, slug: str, max_hours: float, dry_run: bool, force: bool) -> None:
    state = load_state(stage)
    if state.get("kernel_id") and not state.get("cleaned") and not force:
        raise LaneError(f"{stage.name} already has a run ({state['kernel_id']}, {state.get('status')}); "
                        "finish/cleanup it, or pass --force")
    intro, narration, outro = preflight(stage, max_hours)
    owner = kaggle_owner()

    out_dir = stage.parent / f"{stage.name}-kcpu"
    say(f"packing {stage.name} …")
    bundle, digest = build_bundle(stage, out_dir)
    kernel_id, dataset_id = ids_for(owner, slug, digest)
    assert_safe_kernel_ref(kernel_id, owner)
    storyboard = (yaml.safe_load((stage / "job.yaml").read_text(encoding="utf-8")) or {}).get("storyboard") or []
    manifest = {
        "schema": 1, "slug": slug, "kernel_id": kernel_id, "dataset_id": dataset_id,
        "commit": run(["git", "rev-parse", "HEAD"], cwd=REPO), "bundle_sha256": digest,
        "bundle_bytes": bundle.stat().st_size, "narration_seconds": narration,
        "expected_seconds": round(intro + narration + outro, 3), "scenes": len(storyboard),
        "timeout_s": KERNEL_TIMEOUT_S, "stop_after_s": KERNEL_TIMEOUT_S - STOP_MARGIN_S,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out_dir / "dataset-metadata.json").write_text(json.dumps(dataset_metadata(dataset_id), indent=2))
    kmeta = kernel_metadata(kernel_id, dataset_id)
    say(f"bundle {manifest['bundle_bytes'] / 2**20:.0f} MiB, {len(storyboard)} scenes, "
        f"narration {narration / 3600:.2f} h, expected video {manifest['expected_seconds']:.2f}s, "
        f"credential scan clean")
    if dry_run:
        print(json.dumps({"kernel-metadata.json": kmeta, "dataset-metadata.json":
                          dataset_metadata(dataset_id), "manifest.json": manifest}, indent=2))
        say("dry run: nothing uploaded")
        return

    # `kaggle datasets status` answers 403 for this account's access token (Chap 71, 2026-10-12) while
    # `datasets files` works, so presence is read from the file listing; the box re-checks the sha256.
    expected = {BUNDLE_NAME: manifest["bundle_bytes"], "manifest.json": None}
    listing = kaggle("datasets", "files", dataset_id, check=False)
    if dataset_has_files(listing, expected):
        say(f"dataset {dataset_id} already holds this bundle, skipping the upload")
    else:
        say(f"uploading private dataset {dataset_id} ({manifest['bundle_bytes'] / 2**20:.0f} MiB) …")
        out = (kaggle("datasets", "version", "-p", str(out_dir), "-r", "skip", "-q", "-m", digest)
               if parse_dataset_files(listing) else kaggle("datasets", "create", "-p", str(out_dir), "-r", "skip", "-q"))
        if cli_error(out):
            raise LaneError(f"dataset upload refused by Kaggle:\n{out}")
        deadline = time.time() + DATASET_READY_TIMEOUT_S
        while not dataset_has_files(listing := kaggle("datasets", "files", dataset_id, check=False), expected):
            if time.time() > deadline:
                raise LaneError(f"dataset {dataset_id} does not list {BUNDLE_NAME} after "
                                f"{DATASET_READY_TIMEOUT_S // 60} min:\n{listing[-500:]}")
            time.sleep(DATASET_POLL_S)
        say(f"dataset {dataset_id} lists {BUNDLE_NAME} and manifest.json")

    with tempfile.TemporaryDirectory(prefix="kcpu-kernel-") as tmp:
        shutil.copy(BOX_SCRIPT, Path(tmp) / BOX_SCRIPT.name)
        (Path(tmp) / "kernel-metadata.json").write_text(json.dumps(kmeta, indent=2))
        out = kaggle("kernels", "push", "-p", tmp, "-t", str(KERNEL_TIMEOUT_S))
    if "successfully pushed" not in out:
        raise LaneError(f"kernel push not accepted:\n{out}")
    save_state(stage, {**manifest, "owner": owner, "status": "submitted",
                       "submitted_at": time.time(), "bundle_dir": str(out_dir)})
    say(f"pushed {kernel_id} (private, CPU only, timeout {KERNEL_TIMEOUT_S / 3600:.1f} h)")


def latest_box_line(log_text: str) -> str:
    """The newest heartbeat, else the newest timestamped box line (`[  12.3s] …`)."""
    lines = [ln.strip() for ln in log_text.splitlines()]
    beats = [ln for ln in lines if "heartbeat:" in ln]
    stamped = [ln for ln in lines if re.match(r"\[\s*\d+\.\ds\] ", ln)]
    return (beats or stamped or [""])[-1]


def startup_lines(tail: list[str]) -> list[str] | None:
    """The box's lines up to `render start` (python, ffmpeg, font, disk, bundle, encoder) once that
    line is there; None before it."""
    stamped = [line.strip() for line in tail if re.match(r"\[\s*\d+\.\ds\] ", line.strip())]
    for index, line in enumerate(stamped):
        if "render start" in line:
            return stamped[:index + 1]
    return None


def watch(stage: Path) -> None:
    state = load_state(stage)
    need(state, "kernel_id", "submit")
    kernel_id = assert_safe_kernel_ref(state["kernel_id"], state["owner"])
    deadline = state["submitted_at"] + KERNEL_TIMEOUT_S + 1800
    if state.get("status") == "submitted":
        # A re-pushed kernel can still report the previous version's end state for a moment; wait
        # (max 5 min) until this run shows up, so an old COMPLETE is never taken for this one.
        settle = time.time() + 300
        while is_terminal(parse_status(kaggle("kernels", "status", kernel_id, check=False))) \
                and time.time() < settle:
            time.sleep(10)
        state["status"] = "started"
        save_state(stage, state)
    last, unknown, next_log = None, 0, time.time() + LOG_EVERY_S
    while True:
        status = parse_status(kaggle("kernels", "status", kernel_id, check=False))
        unknown = unknown + 1 if status == "unknown" else 0
        if unknown >= MAX_UNKNOWN_POLLS:
            raise LaneError(f"cannot read the status of {kernel_id} {MAX_UNKNOWN_POLLS} times in a row")
        elapsed_h = (time.time() - state["submitted_at"]) / 3600
        if status != last and status != "unknown":
            say(f"{kernel_id}: {status} ({elapsed_h:.2f} h since submit)")
            last = status
        if is_terminal(status):
            break
        if time.time() >= next_log:
            beat = latest_box_line(box_log_so_far(kernel_id))
            if beat:
                say(f"box {beat}")
            next_log = time.time() + LOG_EVERY_S
        if time.time() > deadline:
            raise LaneError(f"{kernel_id} still {status} past the {KERNEL_TIMEOUT_S / 3600:.1f} h timeout")
        time.sleep(POLL_S)
    state.update(status=status, finished_at=time.time())
    save_state(stage, state)
    if status != "complete":
        tail = "\n".join(log_text(kaggle("kernels", "logs", kernel_id, check=False)).splitlines()[-40:])
        raise LaneError(f"{kernel_id} ended {status}. Last log lines:\n{tail}")
    say(f"render COMPLETE on Kaggle CPU after {(state['finished_at'] - state['submitted_at']) / 3600:.2f} h")


def fetch(stage: Path) -> None:
    state = load_state(stage)
    need(state, "kernel_id", "submit")
    if state.get("status") != "complete":
        raise LaneError(f"kernel status is {state.get('status')!r}, run `watch` until it completes")
    dl = stage.parent / f"{stage.name}-dl"
    for attempt in range(1, 4):
        say(f"downloading kernel output (attempt {attempt}) …")
        kaggle("kernels", "output", state["kernel_id"], "-p", str(dl), "-o", "-q", check=False)
        result_path = dl / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("bundle_sha256") != state["bundle_sha256"]:
                raise LaneError("the kernel output belongs to another submission (bundle hash differs)")
            payload = dl / (result["clips_tar"] if result.get("status") == "partial" else result["mp4"])
            if payload.exists() and sha256_file(payload) == result["sha256"]:
                break
        if attempt == 3:
            raise LaneError(f"download incomplete or corrupt in {dl} after 3 attempts")
    if result.get("status") == "partial":
        say(f"the box stopped at its deadline and shipped {result['clips_done']}/{result['scenes']} clips; "
            "finishing the render on this machine …")
        result = complete_locally(stage, dl, result)
        say(f"rendered {result['clips_rendered_locally']} clips + the mux here in "
            f"{result['local_render_seconds'] / 60:.1f} min")
    state.update(fetched=True, dl_dir=str(dl), result=result)
    save_state(stage, state)
    say(f"fetched {result['mp4']} ({result['bytes'] / 1e9:.2f} GB, sha256 ok, "
        f"render {result['render_seconds'] / 3600:.2f} h on {result['cpu_count']} cpu)")


def complete_locally(stage: Path, dl: Path, result: dict) -> dict:
    """Finish a render the box stopped at its deadline. Its clips go into the stage workspace and the
    render runs here with the box's job.yaml (same encoder, overlays baked): the executor skips every
    clip already on disk, so only the missing clips and the stream-copy mux run. The mp4 then lands in
    the download dir, so `finish` treats it like a box-rendered one."""
    leftovers = sorted(p.name for p in (stage / "outputs").glob("*.mp4"))
    if leftovers:
        raise LaneError(f"outputs/ already holds {leftovers}; move it away before finishing the render here")
    workspace = stage / ".videotool/tmp"
    workspace.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dl / result["clips_tar"]) as tar:
        tar.extractall(workspace, filter="data")
    shutil.copy(dl / "job.yaml", stage / "job.yaml")
    started = time.time()
    run([str(VT), "render", str(stage / "job.yaml"), "--preset", "youtube-16x9"], cwd=stage)
    mp4s = sorted((stage / "outputs").glob("*.mp4"))
    if len(mp4s) != 1:
        raise LaneError(f"the local render left {[p.name for p in mp4s]} in outputs/, expected one mp4")
    mp4 = dl / mp4s[0].name
    shutil.move(str(mp4s[0]), str(mp4))
    clips = len(list(workspace.glob("clips/*/scene-[0-9][0-9][0-9][0-9].mp4")))
    return {**result, "status": "complete", "mp4": mp4.name, "bytes": mp4.stat().st_size,
            "sha256": sha256_file(mp4), "clips_rendered_locally": clips - result["clips_done"],
            "local_render_seconds": round(time.time() - started, 1)}


def finish(stage: Path) -> None:
    """modal-runbook step 5 in the same order, then the checks SKILL.md step 5 asks for."""
    state = load_state(stage)
    need(state, "fetched", "fetch")
    if state.get("finished"):
        say("finish already done")
        return
    leftovers = sorted(p.name for p in (stage / "outputs").glob("*.mp4"))
    if leftovers:
        # sfx mixes in place: running it over an already-mixed mp4 would add every cue twice.
        raise LaneError(f"outputs/ already holds {leftovers} from an earlier finish attempt; move it away, "
                        "then re-run finish")
    dl, result = Path(state["dl_dir"]), state["result"]
    shutil.copy(dl / result["mp4"], stage / "outputs" / result["mp4"])
    shutil.copy(dl / "job.yaml", stage / "job.yaml")
    (stage / ".videotool/tmp").mkdir(parents=True, exist_ok=True)
    with tarfile.open(dl / "logs.tar") as tar:
        tar.extractall(stage / ".videotool/tmp", filter="data")
    job = str(stage / "job.yaml")
    sfx_out = run([str(VT), "sfx", job])
    enhance = (yaml.safe_load((stage / "job.yaml").read_text(encoding="utf-8")) or {}).get("enhance") or {}
    cues = (enhance.get("sfx") or {}).get("cues") or []
    if cues and "Mixed SFX onto 1 output(s)" not in sfx_out:
        raise LaneError(f"sfx did not report 'Mixed SFX onto 1 output(s)':\n{sfx_out[-1500:]}")
    say("sfx mixed" if cues else "no sfx cues in job.yaml")
    run([str(VT), "package", job])
    report = json.loads((stage / "outputs/quality-report.json").read_text(encoding="utf-8"))
    failed = [c["name"] for c in report if c["status"] == "fail"]
    if failed:
        raise LaneError(f"package QA failed: {failed}")
    say(f"package QA: {sum(c['status'] == 'pass' for c in report)}/{len(report)} pass, "
        + "; ".join(f"{c['name']}: {c['message']}" for c in report if c["status"] != "pass"))
    run([str(VT), "metadata", job])
    verify(stage)
    # Contact sheet + loudness by section (`.videotool/review/`): findings warn, never block publish.
    for line in run([str(VT), "review", job], check=False).splitlines():
        if line.strip():
            say(line.strip())
    state.update(finished=True)
    save_state(stage, state)


def verify(stage: Path) -> None:
    mp4s = sorted((stage / "outputs").glob("*.mp4"))
    if len(mp4s) != 1:
        raise LaneError(f"expected one mp4 in outputs/, found {[p.name for p in mp4s]}")
    mp4 = mp4s[0]
    streams = json.loads(run(["ffprobe", "-v", "error", "-show_entries",
                              "stream=codec_type,codec_name,width,height", "-of", "json", str(mp4)]))["streams"]
    video = [s for s in streams if s["codec_type"] == "video"]
    audio = [s for s in streams if s["codec_type"] == "audio"]
    if not (video and video[0]["codec_name"] == "h264" and (video[0]["width"], video[0]["height"]) == (1920, 1080)
            and audio and audio[0]["codec_name"] == "aac"):
        raise LaneError(f"streams are not h264 1920x1080 + aac: {streams}")
    intro, narration, outro = expected_seconds(stage)
    expected, actual = intro + narration + outro, media_seconds(mp4, "a:0")
    if abs(actual - expected) > DURATION_TOLERANCE_S:
        raise LaneError(f"audio duration {actual:.2f}s != intro {intro:.2f} + narration {narration:.2f} "
                        f"+ outro {outro:.2f} = {expected:.2f}s")
    video_s = media_seconds(mp4, "v:0")
    if abs(video_s - actual) > VIDEO_AUDIO_SLACK_S:
        raise LaneError(f"video stream {video_s:.2f}s vs audio {actual:.2f}s — more than "
                        f"{VIDEO_AUDIO_SLACK_S}s apart")
    size = mp4.stat().st_size
    if size >= SIZE_CAP_BYTES:
        raise LaneError(f"{mp4.name} is {size / 1e9:.2f} GB, over the 4.5 GB ceiling")
    youtube_srt = stage / "outputs/captions.youtube.srt"
    first, _ = srt_cue_bounds(youtube_srt.read_text(encoding="utf-8"))
    if intro and abs(first - intro) > 0.05:
        raise LaneError(f"captions.youtube.srt starts at {first:.3f}s, intro CTA is {intro:.3f}s")
    say(f"verified {mp4.name}: h264 1920x1080 + aac, audio {actual:.2f}s (expected {expected:.2f}), "
        f"video {video_s:.2f}s, {size / 1e9:.2f} GB, youtube srt starts {first:.3f}s")


def publish(stage: Path, remote: str) -> None:
    state = load_state(stage)
    need(state, "finished", "finish")
    if ":" not in remote or "_VIDEOTOOL_SHARED" in remote:
        raise LaneError(f"--remote must be the episode folder on an rclone remote, got {remote!r}")
    dest = remote.rstrip("/") + "/outputs"
    say(f"publishing to {dest} …")
    run(["rclone", "copy", str(stage / "outputs"), dest, "--exclude", "thumbnail-candidate-*.jpg",
         "--transfers", "4"])
    remote_sizes = {}
    for line in run(["rclone", "lsl", dest, "--max-depth", "1"]).splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4:
            remote_sizes[parts[3]] = int(parts[0])
    local = {p.name: p.stat().st_size for p in (stage / "outputs").iterdir()
             if p.is_file() and not fnmatch.fnmatch(p.name, "thumbnail-candidate-*.jpg")}
    mismatched = {n: (s, remote_sizes.get(n)) for n, s in local.items() if remote_sizes.get(n) != s}
    if mismatched:
        raise LaneError(f"published sizes differ (local, remote): {mismatched}")
    state.update(published=True, remote=remote)
    save_state(stage, state)
    say(f"published {len(local)} files, sizes match")


def cleanup(stage: Path, force: bool) -> None:
    state = load_state(stage)
    need(state, "kernel_id", "submit")
    if not state.get("published") and not force:
        raise LaneError("not published yet — cleanup would delete the only copy on Kaggle (use --force)")
    kernel_id = assert_safe_kernel_ref(state["kernel_id"], state["owner"])
    errors = []
    for kind, ref in (("kernels", kernel_id), ("datasets", state["dataset_id"])):
        out = kaggle(kind, "delete", ref, "-y", check=False)
        say(f"deleting {kind[:-1]} {ref}: {out or 'ok'}")
        if cli_error(out) and "not found" not in out.lower():
            errors.append(f"{ref}: {out}")
    if errors:
        raise LaneError("Kaggle refused to delete: " + "; ".join(errors))
    state.update(cleaned=True)
    save_state(stage, state)


def purge(stage: Path) -> None:
    """Free this machine: purge_stage.py re-checks the published sizes, keeps the review folder and
    deletes the stage (this state file with it) plus its -dl/-kcpu siblings. Waits for `cleanup`, so a
    Kaggle refusal keeps the state needed to retry it."""
    state = load_state(stage)
    need(state, "cleaned", "cleanup")
    out = run([sys.executable, str(PURGE_SCRIPT), str(stage),
               "--published-to", state["remote"].rstrip("/") + "/outputs"])
    for line in out.splitlines():
        say(line)


def status(stage: Path) -> None:
    state = load_state(stage)
    print(json.dumps({k: v for k, v in state.items() if k != "result"}, indent=2, ensure_ascii=False))
    if state.get("kernel_id") and not state.get("cleaned"):
        say(parse_status(kaggle("kernels", "status", state["kernel_id"], check=False)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("cmd", choices=("run", "submit", "watch", "fetch", "finish", "publish", "cleanup", "purge",
                                           "status"))
    parser.add_argument("stage", type=Path, help="the stage prepared with `videotool prepare --target cloud`")
    parser.add_argument("--slug", help="episode slug (default: the stage folder name)")
    parser.add_argument("--remote", help="rclone path of the episode folder, e.g. gdrive:…/Chap 71")
    parser.add_argument("--max-narration-hours", type=float, default=MAX_NARRATION_H)
    parser.add_argument("--dry-run", action="store_true", help="submit: print metadata, upload nothing")
    parser.add_argument("--force", action="store_true", help="submit over an open run / cleanup unpublished")
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
        steps = {"watch": [watch], "fetch": [fetch], "finish": [finish], "status": [status],
                 "publish": [lambda s: publish(s, args.remote)], "cleanup": [lambda s: cleanup(s, args.force)],
                 "purge": [purge],
                 "run": [watch, fetch, finish, lambda s: publish(s, args.remote), lambda s: cleanup(s, False),
                         purge]}
        for step in steps.get(args.cmd, []):
            step(stage)
    except LaneError as exc:
        say(f"FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
