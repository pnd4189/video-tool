"""Render one prepared episode on a Kaggle CPU-only kernel. Runbook: references/kaggle-cpu-runbook.md.

Kaggle runs this file as the kernel's code; `kaggle_cpu_render.py submit` pushes it. The episode arrives
as a private dataset holding `bundle.vtb` (repo/ = the committed videotool code, job/ = the stage
prepared locally with `videotool prepare --target cloud`) and `manifest.json`. No credential reaches
this box: it reads only the dataset and writes only /kaggle/working, which the local driver downloads.

The render tail is the one modal_render.py runs (parallax-link, parallax check, static title cards,
encoder probe + bitrate cap, `videotool render --preset youtube-16x9`), on x264 because the box has
no GPU. sfx / package / metadata run locally afterwards.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

INPUT_ROOT = Path("/kaggle/input")
WORK = Path("/kaggle/working")
BUNDLE_NAME = "bundle.vtb"  # an uncompressed tar; a neutral suffix so Kaggle never unpacks it on upload
SCRATCH_CANDIDATES = (Path("/tmp"), Path("/kaggle/tmp"))
MIN_FREE_GIB = 25  # clips + final mp4 of a ~2h episode (modal_render.py measured the same need)
HEARTBEAT_S = 120


class BoxError(RuntimeError):
    """A check failed before or after the render; the message names the cause."""


def find_manifest(root: Path, max_depth: int = 4) -> Path:
    """The single manifest.json with the bundle beside it. Kaggle mounts a dataset at
    /kaggle/input/<slug>/ or /kaggle/input/datasets/<owner>/<slug>/ depending on the image."""
    hits = []
    for depth in range(1, max_depth + 1):
        pattern = "/".join(["*"] * (depth - 1) + ["manifest.json"])
        hits += [p for p in root.glob(pattern) if (p.parent / BUNDLE_NAME).is_file()]
    if len(hits) != 1:
        raise BoxError(f"expected one manifest.json beside a {BUNDLE_NAME} under {root}, found {hits}")
    return hits[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(manifest: dict, bundle: Path) -> None:
    size = bundle.stat().st_size
    if size != manifest.get("bundle_bytes"):
        raise BoxError(f"{bundle.name} is {size} bytes, manifest says {manifest.get('bundle_bytes')}")
    if sha256_file(bundle) != manifest.get("bundle_sha256"):
        raise BoxError(f"{bundle.name} sha256 does not match the manifest (corrupt or stale upload)")


def require_cpu_encoder(encoder: str) -> str:
    """This lane renders with x264 only; anything else means the box or the probe is not what we
    pushed, and the clips would not match what the runbook's timings assume."""
    if not encoder.startswith("libx264"):
        raise BoxError(f"encoder {encoder!r} is not x264 — this kernel must be CPU-only")
    return encoder


def free_gib(path: Path) -> float:
    return shutil.disk_usage(path).free / 2**30


def pick_scratch(candidates: tuple[Path, ...] = SCRATCH_CANDIDATES, min_free: float = MIN_FREE_GIB) -> Path:
    """The existing candidate with the most free space; refuse when even that is too small."""
    present = [c for c in candidates if c.is_dir()]
    best = max(present, key=free_gib, default=None)
    if best is None or free_gib(best) < min_free:
        sizes = {str(c): round(free_gib(c), 1) for c in present}
        raise BoxError(f"need {min_free} GiB of scratch space, free GiB: {sizes}")
    return best


def clips_done(job: Path) -> int:
    return len(glob.glob(str(job / ".videotool/tmp/clips/*/scene-[0-9][0-9][0-9][0-9].mp4")))


def storyboard_total(job_yaml: Path) -> int:
    import yaml  # noqa: PLC0415 — installed with videotool

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    return len(data.get("storyboard") or [])


def save_logs(logs: Path, render_log: Path) -> None:
    if logs.exists():
        with tarfile.open(WORK / "logs.tar", "w") as tar:
            tar.add(logs, arcname="logs")
    shutil.copy(render_log, WORK / "render.log")


def _sh(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    except FileNotFoundError:
        return f"{cmd[0]}: not found"
    return (r.stdout + r.stderr).strip()


def _videotool() -> str:
    return shutil.which("videotool") or str(Path(sys.executable).with_name("videotool"))


def main() -> None:
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)

    ram_gib = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    log(f"box: python {platform.python_version()} | {os.cpu_count()} cpu | {ram_gib:.1f} GiB RAM")
    log("ffmpeg: " + _sh(["ffmpeg", "-hide_banner", "-version"]).splitlines()[0])
    log("font: " + _sh(["fc-match", "Arial"]))
    log("disk free GiB: " + ", ".join(f"{p} {free_gib(p):.1f}" for p in (*SCRATCH_CANDIDATES, WORK) if p.is_dir()))
    if shutil.which("ffmpeg") is None:
        raise BoxError("ffmpeg is not on PATH in this Kaggle image")
    unpack = pick_scratch() / "vt"

    manifest_path = find_manifest(INPUT_ROOT)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = manifest_path.parent / BUNDLE_NAME
    verify_bundle(manifest, bundle)
    log(f"bundle ok: {manifest['slug']} @ {manifest['commit'][:12]} ({manifest['bundle_bytes'] / 2**20:.0f} MiB)")

    with tarfile.open(bundle) as tar:
        tar.extractall(unpack, filter="data")
    repo, job = unpack / "repo", unpack / "job"
    log(f"unpacked to {unpack}")
    (job / "media").mkdir(exist_ok=True)  # render validates media/; an empty dir is not archived

    pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", str(repo)],
                         capture_output=True, text=True, errors="replace")
    if pip.returncode != 0:
        print("\n".join((pip.stdout + pip.stderr).splitlines()[-30:]), flush=True)
        raise BoxError(f"pip install of the shipped videotool failed (exit {pip.returncode})")
    shown = _sh([sys.executable, "-m", "pip", "show", "videotool"]).splitlines()
    log("videotool: " + next((line for line in shown if line.startswith("Version")), "version unknown"))

    sys.path.insert(0, str(repo / "Colab"))
    import cloud_render_runner as rr  # noqa: PLC0415 — the runner module the Kaggle notebooks use

    job_yaml, creative = job / "job.yaml", job / "creative.yaml"
    if (job / "Parallax").exists():
        rr.vc._run_cli(["parallax-link", str(job_yaml), "--clips-dir", str(job / "Parallax")])
    rr._check_parallax_source(job, job_yaml, creative if creative.exists() else None)
    rr._keep_title_cards_static(job, job_yaml)
    encoder = require_cpu_encoder(
        rr._apply_bitrate_cap(rr.probe_encoder(allow_cpu=True), rr._bitrate_cap(creative)))
    rr._set_encoder(job_yaml, encoder)
    log(f"encoder pinned: {encoder}")

    workers = max(1, os.cpu_count() or 1)
    total = storyboard_total(job_yaml)
    env = {**os.environ, "VIDEOTOOL_SCENE_WORKERS": str(workers)}
    stop = threading.Event()
    t_render = time.time()

    def heartbeat() -> None:
        while not stop.wait(HEARTBEAT_S):
            done = clips_done(job)
            elapsed = time.time() - t_render
            eta = f", clip ETA {elapsed / done * (total - done) / 60:.0f} min" if 0 < done < total else ""
            used = _sh(["du", "-sh", str(job)]).split()[0]
            load = open("/proc/loadavg").read().split()[0]
            log(f"heartbeat: {done}/{total} clips, {elapsed / 60:.0f} min{eta}, job dir {used}, load {load}")

    threading.Thread(target=heartbeat, daemon=True).start()
    log(f"render start ({workers} scene workers, {total} scenes)")
    render_log = unpack / "render.log"
    with render_log.open("w", encoding="utf-8", errors="replace") as fh:
        rc = subprocess.run([_videotool(), "render", str(job_yaml), "--preset", "youtube-16x9"],
                            cwd=job, env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    stop.set()
    render_seconds = time.time() - t_render
    log(f"render finished rc={rc} in {render_seconds / 60:.1f} min")
    print("\n".join(render_log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]), flush=True)

    logs = job / ".videotool/tmp/logs"
    if rc != 0:
        rr._dump_render_logs(job)
        save_logs(logs, render_log)
        raise BoxError(f"videotool render exited {rc}")

    mp4s = sorted((job / "outputs").glob("*.mp4"))
    if len(mp4s) != 1:
        raise BoxError(f"expected exactly one mp4 in outputs/, found {[p.name for p in mp4s]}")
    probe = json.loads(_sh(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration:stream=codec_name,width,height", "-of", "json", str(mp4s[0])]))
    digest = sha256_file(mp4s[0])
    result = {
        "mp4": mp4s[0].name, "bytes": mp4s[0].stat().st_size, "sha256": digest,
        "duration": float(probe["format"]["duration"]),
        "streams": [{k: s.get(k) for k in ("codec_name", "width", "height")} for s in probe["streams"]],
        "encoder": encoder, "render_seconds": round(render_seconds, 1), "scenes": total,
        "commit": manifest["commit"], "bundle_sha256": manifest["bundle_sha256"],
        "python": platform.python_version(),
        "ffmpeg": _sh(["ffmpeg", "-hide_banner", "-version"]).splitlines()[0], "cpu_count": os.cpu_count(),
    }

    # Flat files only: the mp4 at the top, the logs as one tar, so the download layout cannot matter.
    shutil.move(str(mp4s[0]), str(WORK / mp4s[0].name))
    save_logs(logs, render_log)  # `package` wants .videotool/tmp/logs back locally
    shutil.copy(job_yaml, WORK / "job.yaml")
    (WORK / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log(f"DONE {result['mp4']} {result['bytes']} bytes {result['duration']:.2f}s")


if __name__ == "__main__":
    main()
