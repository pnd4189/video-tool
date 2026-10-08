"""Render one prepared episode on Modal (T4 + NVENC). Runbook: references/modal-runbook.md.

Does the render step only. It ships the job folder prepared locally with
`videotool prepare <stage> --target cloud --creative <creative.yaml>`, replays the tail of
Colab/cloud_render_runner.render_job on a T4 (parallax-link, parallax check, static title cards,
NVENC probe + bitrate cap, `videotool render --preset youtube-16x9`) and leaves the outputs, the
pinned job.yaml and the ffmpeg logs in a Volume. sfx / package / metadata run locally afterwards.

    VT_JOB_DIR=<prepared stage> VT_SLUG=<binh-thien-chapNN> modal run <this file>

Optional: VT_WORKERS (scene workers = cores, default 8), VT_TIMEOUT_S (default 10800).
Only `modal run`: never deploy, schedule or keep warm. Cost and limits: modal-runbook.md.
"""
import os
from pathlib import Path

import modal

LOCAL = modal.is_local()  # this module is imported again inside the container
SLUG = os.environ.get("VT_SLUG", "")
JOB = os.environ.get("VT_JOB_DIR", "")
WORKERS = int(os.environ.get("VT_WORKERS", "8"))
TIMEOUT_S = int(os.environ.get("VT_TIMEOUT_S", "10800"))
if LOCAL and not (SLUG and JOB):
    raise SystemExit("set VT_SLUG and VT_JOB_DIR, e.g. VT_JOB_DIR=$HOME/.cache/videotool/<stage> VT_SLUG=binh-thien-chap67")
REPO = Path(__file__).resolve().parents[4] if LOCAL else Path("/repo")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "fontconfig", "fonts-liberation", "fonts-dejavu-core")
    .add_local_file(f"{REPO}/pyproject.toml", "/repo/pyproject.toml", copy=True)
    .add_local_file(f"{REPO}/README.md", "/repo/README.md", copy=True)
    .add_local_dir(f"{REPO}/src", "/repo/src", copy=True, ignore=["**/__pycache__"])
    .run_commands("pip install /repo")
    .env({"VT_SLUG": SLUG, "VT_JOB_DIR": JOB, "VT_WORKERS": str(WORKERS), "VT_TIMEOUT_S": str(TIMEOUT_S)})
    .add_local_dir(f"{REPO}/Colab", "/opt/colab", ignore=["*.ipynb", "**/__pycache__"])
    .add_local_dir(JOB or "/nonexistent", "/job_src")
)
app = modal.App(f"vt-{SLUG}", image=image)
vol = modal.Volume.from_name(f"vt-{SLUG}", create_if_missing=True)


@app.function(gpu="T4", cpu=WORKERS, memory=32768, timeout=TIMEOUT_S, retries=0, volumes={"/vol": vol})
def render() -> str:
    import glob
    import shutil
    import subprocess
    import sys
    import threading
    import time

    t0 = time.time()
    lines: list[str] = []

    def log(msg: str) -> None:
        line = f"[{time.time() - t0:7.1f}s] {msg}"
        print(line, flush=True)
        lines.append(line)

    def sh(cmd: str) -> str:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors="replace")
        return (r.stdout + r.stderr).strip()

    log("ffmpeg: " + sh("ffmpeg -version | head -1"))
    log("videotool: " + sh("pip show videotool | grep -i '^Version'"))
    log("gpu: " + sh("nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"))
    log(f"cpu_count(host)={os.cpu_count()}")
    log("fonts: " + sh("fc-match Arial") + " | " + sh("fc-list | wc -l") + " font files")
    log("disk /tmp:\n" + sh("df -h /tmp | tail -1"))
    free_gib = shutil.disk_usage("/tmp").free / 2**30
    if free_gib < 25:
        raise RuntimeError(f"only {free_gib:.1f} GiB free in /tmp, need ~25 GiB for clips + final mp4")

    job = Path("/tmp/job")
    shutil.copytree("/job_src", job)
    (job / "media").mkdir(exist_ok=True)  # Modal does not ship empty dirs; render validates media/
    log(f"job copied to local disk ({sh('du -sh /tmp/job').split()[0]})")

    sys.path.insert(0, "/opt/colab")
    import cloud_render_runner as rr  # the runner module the Kaggle notebooks use

    job_yaml = job / "job.yaml"
    creative = job / "creative.yaml"
    if (job / "Parallax").exists():
        rr.vc._run_cli(["parallax-link", str(job_yaml), "--clips-dir", str(job / "Parallax")])
    rr._check_parallax_source(job, job_yaml, creative if creative.exists() else None)
    rr._keep_title_cards_static(job, job_yaml)
    encoder = rr._apply_bitrate_cap(rr.probe_encoder(allow_cpu=False), rr._bitrate_cap(creative))
    rr._set_encoder(job_yaml, encoder)
    log(f"encoder pinned: {encoder}")

    env = {**os.environ, "VIDEOTOOL_SCENE_WORKERS": str(WORKERS)}
    stop = threading.Event()

    def heartbeat() -> None:
        while not stop.wait(120):
            clips = len(glob.glob(str(job / ".videotool/tmp/clips/*/scene-[0-9][0-9][0-9][0-9].mp4")))
            used = sh("du -sh /tmp/job | cut -f1")
            log(f"heartbeat: {clips} scene clip(s) done, job dir {used}, load {open('/proc/loadavg').read().split()[0]}")

    threading.Thread(target=heartbeat, daemon=True).start()
    log(f"render start ({WORKERS} scene workers)")
    t_render = time.time()
    render_log = Path("/tmp/render.log")
    with render_log.open("w", encoding="utf-8", errors="replace") as fh:
        rc = subprocess.run(
            ["videotool", "render", str(job_yaml), "--preset", "youtube-16x9"],
            cwd=job, env=env, stdout=fh, stderr=subprocess.STDOUT,
        ).returncode
    stop.set()
    log(f"render finished rc={rc} in {time.time() - t_render:.0f}s")
    tail = "\n".join(render_log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
    log("render log tail:\n" + tail)
    if rc != 0:
        rr._dump_render_logs(job)
        raise RuntimeError(f"videotool render exited {rc}")

    mp4s = sorted((job / "outputs").glob("*.mp4"))
    log("outputs: " + sh("ls -la /tmp/job/outputs"))
    if len(mp4s) != 1:
        raise RuntimeError(f"expected exactly one mp4 in outputs/, found {[p.name for p in mp4s]}")
    log("ffprobe: " + sh(f"ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height -of compact '{mp4s[0]}'"))

    shutil.copytree(job / "outputs", "/vol/outputs", dirs_exist_ok=True)
    shutil.copytree(job / ".videotool/tmp/logs", "/vol/logs", dirs_exist_ok=True)  # `package` wants these
    shutil.copy(job_yaml, "/vol/job.yaml")
    shutil.copy(render_log, "/vol/render.log")
    vol.commit()
    log("copied outputs + logs + job.yaml + render.log to volume, committed")
    return "\n".join(lines)


@app.local_entrypoint()
def main():
    print("\n=== SUMMARY ===\n" + render.remote())
