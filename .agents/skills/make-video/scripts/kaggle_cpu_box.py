"""Render one prepared episode on a Kaggle CPU-only kernel. Runbook: references/kaggle-cpu-runbook.md.

Kaggle runs this file as the kernel's code; `kaggle_cpu_render.py submit` pushes it. The episode arrives
as a private dataset holding `bundle.vtb` (repo/ = the committed videotool code, job/ = the stage
prepared locally with `videotool prepare --target cloud`) and `manifest.json`. No credential reaches
this box: it reads only the dataset and writes only /kaggle/working, which the local driver downloads.

The render tail is the one modal_render.py runs (parallax-link, parallax check, static title cards,
encoder probe + bitrate cap, `videotool render --preset youtube-16x9`), on x264 `faster` with the
overlays baked into the scene clips (`render.bake_overlays`), because the box has 4 CPUs and no GPU.
sfx / package / metadata run locally afterwards.

Safety net: at `stop_after_s` (manifest) the box stops the render, ships every finished clip as
`clips.tar` with a `partial` result, and exits cleanly, so the local driver can finish the render
instead of losing the run to Kaggle's session wall (Chap 71 was cut at 11.5 h with nothing saved).

The Colab CLI lane (colab_render.py) runs this same file on a Colab CPU VM, with VT_BOX_INPUT and
VT_BOX_WORK pointing the two folders below at /content.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

INPUT_ROOT = Path(os.environ.get("VT_BOX_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("VT_BOX_WORK", "/kaggle/working"))
BUNDLE_NAME = "bundle.vtb"  # an uncompressed tar; a neutral suffix so Kaggle never unpacks it on upload
CLIPS_TAR = "clips.tar"
SCRATCH_CANDIDATES = (Path("/tmp"), Path("/kaggle/tmp"))
MIN_FREE_GIB = 25  # clips + final mp4 of a ~2h episode (modal_render.py measured the same need)
HEARTBEAT_S = 120
# x264 `faster` + overlays baked per clip: ~1.9 h of box time per video-hour instead of ~4 h
# (Chap 71 trial + bench, 2026-10-13). The creative's bitrate cap picks the -2500k/-2200k variant.
CPU_PROFILE = "libx264-faster-capped"


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


def clip_total(job_yaml: Path) -> int:
    """Scene clips the render makes: the storyboard plus the intro/outro CTA cards (Chap 71's
    heartbeat read 304/302 because it counted the storyboard only)."""
    import yaml  # noqa: PLC0415 — installed with videotool

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    inputs = data.get("inputs") or {}
    return len(data.get("storyboard") or []) + sum(1 for key in ("intro_cta", "outro_cta") if inputs.get(key))


def pin_render(job_yaml: Path, encoder: str) -> None:
    """The CPU lane's render settings: the x264 profile and overlays baked into the scene clips."""
    import yaml  # noqa: PLC0415

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    data.setdefault("render", {}).update(encoder=encoder, bake_overlays=True)
    job_yaml.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def wait_or_stop(proc: subprocess.Popen, stop_at: float | None, poll_s: float = 30) -> int | None:
    """The render's exit code, or None when it was stopped at `stop_at`. The render runs in its own
    process group, so the stop reaches videotool and every ffmpeg it started; an interrupted clip only
    leaves a .part file, never a truncated clip."""
    while True:
        try:
            return proc.wait(timeout=poll_s)
        except subprocess.TimeoutExpired:
            if stop_at is not None and time.time() >= stop_at:
                break
    for sig, grace in ((signal.SIGTERM, 60), (signal.SIGKILL, 30)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            proc.wait(timeout=grace)
            break
        except subprocess.TimeoutExpired:
            continue
    return None


def ship_clips(job: Path, dest: Path) -> dict:
    """Every finished scene clip (never a .part) in one uncompressed tar, laid out as the workspace
    expects (`clips/<preset>/scene-NNNN.mp4`), so the local driver resumes the render from them."""
    root = job / ".videotool/tmp"
    clips = sorted(root.glob("clips/*/scene-[0-9][0-9][0-9][0-9].mp4"))
    need_gib = sum(p.stat().st_size for p in clips) / 2**30 + 1
    if free_gib(dest.parent) < need_gib:
        raise BoxError(f"{dest.parent} has {free_gib(dest.parent):.1f} GiB free, the clips need {need_gib:.1f}")
    with tarfile.open(dest, "w") as tar:
        for clip in clips:
            tar.add(clip, arcname=clip.relative_to(root).as_posix())
    return {"clips_tar": dest.name, "clips_done": len(clips), "bytes": dest.stat().st_size,
            "sha256": sha256_file(dest)}


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
    require_cpu_encoder(rr.probe_encoder(allow_cpu=True))
    encoder = require_cpu_encoder(rr._apply_bitrate_cap(CPU_PROFILE, rr._bitrate_cap(creative)))
    pin_render(job_yaml, encoder)
    log(f"encoder pinned: {encoder}, overlays baked into the scene clips")

    workers = max(1, os.cpu_count() or 1)
    total = clip_total(job_yaml)
    stop_at = t0 + manifest["stop_after_s"] if manifest.get("stop_after_s") else None
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
    stop_note = f", stops at {(stop_at - t0) / 3600:.2f} h to ship finished clips" if stop_at else ""
    log(f"render start ({workers} scene workers, {total} scenes{stop_note})")
    render_log = unpack / "render.log"
    with render_log.open("w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen([_videotool(), "render", str(job_yaml), "--preset", "youtube-16x9"],
                                cwd=job, env=env, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        rc = wait_or_stop(proc, stop_at)
    stop.set()
    render_seconds = time.time() - t_render
    log(f"render {'stopped at the deadline' if rc is None else f'finished rc={rc}'} in {render_seconds / 60:.1f} min")
    print("\n".join(render_log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]), flush=True)

    logs = job / ".videotool/tmp/logs"
    common = {
        "encoder": encoder, "render_seconds": round(render_seconds, 1), "scenes": total,
        "commit": manifest["commit"], "bundle_sha256": manifest["bundle_sha256"],
        "python": platform.python_version(),
        "ffmpeg": _sh(["ffmpeg", "-hide_banner", "-version"]).splitlines()[0], "cpu_count": os.cpu_count(),
    }
    if rc is None:
        shipped = ship_clips(job, WORK / CLIPS_TAR)
        save_logs(logs, render_log)
        shutil.copy(job_yaml, WORK / "job.yaml")
        result = {"status": "partial", **shipped, **common}
        (WORK / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        log(f"PARTIAL {shipped['clips_done']}/{total} clips shipped in {CLIPS_TAR} "
            f"({shipped['bytes'] / 2**30:.2f} GiB); the local driver finishes the render")
        return
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
        "status": "complete", "mp4": mp4s[0].name, "bytes": mp4s[0].stat().st_size, "sha256": digest,
        "duration": float(probe["format"]["duration"]),
        "streams": [{k: s.get(k) for k in ("codec_name", "width", "height")} for s in probe["streams"]],
        **common,
    }

    # Flat files only: the mp4 at the top, the logs as one tar, so the download layout cannot matter.
    shutil.move(str(mp4s[0]), str(WORK / mp4s[0].name))
    save_logs(logs, render_log)  # `package` wants .videotool/tmp/logs back locally
    shutil.copy(job_yaml, WORK / "job.yaml")
    (WORK / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    log(f"DONE {result['mp4']} {result['bytes']} bytes {result['duration']:.2f}s")


if __name__ == "__main__":
    main()
