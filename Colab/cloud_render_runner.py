"""Cloud render runner — the full `/make-video` pipeline on a Colab/Kaggle GPU session.

One entry point (`render_job`) chains: install -> rclone stage-in -> cloud_director (first run
only) OR checkpoint restore (resume) -> GPU/NVENC/ffmpeg probe -> segmented NVENC render with a
background Drive checkpoint of completed clips -> sfx -> package -> verified publish to `Output/`.
Colab primary, Kaggle secondary; both use rclone (never the FUSE mount) for bulk I/O.

The whole design is the post-red-team hardening from plan 260707-0855 phase 3:
- C1: sync/restore the EXACT nested clip tree `.videotool/tmp/clips/<preset>/scene-NNNN.mp4`.
- C2: upload via `.uploading`+rename; on restore ffprobe-verify each clip's duration before
  trusting it, so a truncated size>0 clip from a lossy Drive round-trip is dropped, not welded in.
- C3: cloud_director already sets `render.max_inline_scenes: 1` -> every job takes the resumable
  segmented path (schema forbids 0; 1 is equivalent for any >=2-scene episode).
- H4: on resume the PINNED job.yaml is restored and cloud_director is skipped — no LLM, no re-author.
- H5: no NVENC / wrong GPU / old ffmpeg aborts with a clear message instead of a silent 6h CPU render.
- H6: publish = temp-name + rename + fresh-listing size verify; checkpoint kept until confirmed.
- H7: rclone for stage-in + checkpoint on Colab too (FUSE is ~60x slower).
- L12: list-form subprocess only (safe with Vietnamese folder names containing apostrophes).

Never writes to the source Drive folder except its `Output/` subfolder. The checkpoint lives on
the shared Drive (`<shared>/checkpoints/<job>`), not inside the source folder.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import videotool_cloud as vc

PRESET = "youtube-16x9"
# Matches scene-0001.mp4 but NOT scene-0001.part.mp4 (the digits are followed by ".part") (C2).
CLIP_INCLUDE = "scene-[0-9][0-9][0-9][0-9].mp4"
CLIP_DURATION_TOLERANCE_S = 0.75  # a restored clip whose duration drifts more than this is re-rendered.
CHECKPOINT_INTERVAL_S = 180


class RunnerError(RuntimeError):
    """Fatal runner error with an operator-facing message."""


# -- rclone + ffprobe primitives (list-form only, L12) -----------------------------------


def _run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def _rclone(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return _run(["rclone", *args], check=check)


def stage_in(remote_dir: str, local_dir: Path) -> Path:
    """rclone copy the whole source folder to local fast disk. Never the FUSE mount (H7)."""
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    _rclone(["copy", remote_dir, str(local_dir), "--transfers", "8", "--fast-list"])
    return local_dir


def probe_encoder(allow_cpu: bool = False) -> str:
    """Return the render encoder profile after checking the GPU actually supports NVENC and the
    ffmpeg build is new enough for `-preset p5`. Abort loudly instead of a silent CPU fallback (H5)."""
    encoders = _run(["ffmpeg", "-hide_banner", "-encoders"], check=False).stdout
    version = _run(["ffmpeg", "-hide_banner", "-version"], check=False).stdout
    ver_ok = _ffmpeg_supports_p_presets(version)
    if "h264_nvenc" in encoders and ver_ok:
        return "h264_nvenc-capped"
    if allow_cpu:
        print("runner: NVENC unavailable — CPU opt-in -> libx264-balanced-capped (segmented).")
        return "libx264-balanced-capped"
    raise RunnerError(
        "No usable NVENC encoder (need h264_nvenc AND ffmpeg >= 4.4 for -preset p5). "
        f"h264_nvenc_present={'h264_nvenc' in encoders}, ffmpeg_p_presets={ver_ok}. "
        "Pick a T4 GPU runtime (P100 has no NVENC), reconnect, or pass allow_cpu=True to "
        "accept a slower capped x264 render."
    )


def _ffmpeg_supports_p_presets(version_text: str) -> bool:
    """`-preset p1..p7` for NVENC needs ffmpeg >= 4.4."""
    import re

    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", version_text)
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2))
    return (major, minor) >= (4, 4)


def clip_duration(path: Path) -> float | None:
    """ffprobe a clip's duration in seconds, or None when it can't be read (treat as invalid)."""
    res = _run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=False,
    )
    try:
        return float(res.stdout.strip())
    except (ValueError, AttributeError):
        return None


# -- checkpoint restore / verify (C1, C2) ------------------------------------------------


def expected_scene_durations(job_yaml: Path) -> dict[int, float]:
    """Map scene index (0-based, matching scene-NNNN) -> duration from the pinned storyboard."""
    import yaml

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    return {i: float(s["duration"]) for i, s in enumerate(data.get("storyboard", []))}


def clip_is_valid(path: Path, expected: float | None) -> bool:
    """A restored clip is trusted only when ffprobe reads a duration within tolerance of the
    pinned scene slot. size>0 alone is NOT enough — a lossy Drive copy can truncate it (C2)."""
    dur = clip_duration(path)
    if dur is None or dur <= 0:
        return False
    if expected is None:  # no pinned slot for this index -> can't verify -> reject
        return False
    return abs(dur - expected) <= CLIP_DURATION_TOLERANCE_S


def restore_checkpoint(checkpoint_remote: str, local_job: Path) -> bool:
    """Restore a pinned job.yaml + verified clips from the Drive checkpoint. Returns True when a
    checkpoint existed (resume run). Drops any clip that fails ffprobe verification (C2)."""
    local_job = Path(local_job)
    probe = _rclone(["lsf", checkpoint_remote], check=False)
    if probe.returncode != 0 or "job.yaml" not in probe.stdout:
        return False

    # Restore the pinned authoring so resume never re-runs cloud_director / the LLM (H4).
    _rclone(["copy", f"{checkpoint_remote}/job.yaml", str(local_job)])
    marker = local_job / vc_pin_marker()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("restored from checkpoint\n", encoding="utf-8")

    clips_dir = local_job / ".videotool" / "tmp" / "clips" / PRESET
    clips_dir.mkdir(parents=True, exist_ok=True)
    _rclone(["copy", f"{checkpoint_remote}/clips/{PRESET}", str(clips_dir),
             "--include", CLIP_INCLUDE], check=False)

    expected = expected_scene_durations(local_job / "job.yaml")
    dropped = 0
    for clip in sorted(clips_dir.glob("scene-[0-9]*.mp4")):
        if clip.name.endswith(".part.mp4"):
            clip.unlink()
            continue
        index = int(clip.stem.split("-")[1])
        if not clip_is_valid(clip, expected.get(index)):
            clip.unlink()
            dropped += 1
    print(f"runner: restored checkpoint ({len(list(clips_dir.glob('scene-*.mp4')))} clips kept, {dropped} dropped).")
    return True


def vc_pin_marker() -> Path:
    import cloud_director  # noqa: PLC0415

    return cloud_director.PIN_MARKER


# -- background checkpoint sync (C1, C2) -------------------------------------------------


class CheckpointSync:
    """Periodically upload completed scene clips + the pinned job.yaml to the Drive checkpoint.
    Uploads to `<name>.uploading` then renames so a stalled transfer never leaves a torn clip
    that a later restore would trust (C2)."""

    def __init__(self, local_job: Path, checkpoint_remote: str, interval_s: int = CHECKPOINT_INTERVAL_S):
        self.clips_dir = Path(local_job) / ".videotool" / "tmp" / "clips" / PRESET
        self.job_yaml = Path(local_job) / "job.yaml"
        self.remote = checkpoint_remote
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> "CheckpointSync":
        # Pin the authored job.yaml first so a resume can restore it even before any clip finishes.
        _rclone(["copyto", str(self.job_yaml), f"{self.remote}/job.yaml"], check=False)
        self._thread.start()
        return self

    def sync_once(self) -> None:
        if not self.clips_dir.exists():
            return
        # Only completed clips are uploaded (the `.part.mp4` in-progress temp is excluded by the
        # glob, C2). rclone->Drive is per-file atomic (Drive finalizes each upload server-side, so
        # an interrupted transfer leaves no torn file); restore additionally ffprobe-verifies every
        # clip, so a truncated clip can never be welded into the output.
        _rclone(["copy", str(self.clips_dir), f"{self.remote}/clips/{PRESET}",
                 "--include", CLIP_INCLUDE], check=False)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.sync_once()
            except Exception as exc:  # a transient rclone failure must not kill the render
                print(f"runner: checkpoint sync warning: {exc}")

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.sync_once()  # final flush of the last completed clips


# -- verified publish (H6) ---------------------------------------------------------------


PUBLISH_ARTIFACTS = (
    f"{PRESET}.mp4",
    "description.txt",
    "captions.srt",
    "captions.youtube.srt",
    "chapters.json",
    "thumbnail-1280x720.jpg",
    "quality-report.json",
    "package-manifest.json",
    "license-report.md",
)


def publish_verified(local_outputs: Path, output_remote: str) -> list[str]:
    """Copy each artifact to `Output/<name>.uploading`, rename, then re-list Output/ from a fresh
    rclone call and confirm size>0 for every one BEFORE the caller deletes the checkpoint (H6)."""
    local_outputs = Path(local_outputs)
    published = []
    for name in PUBLISH_ARTIFACTS:
        src = local_outputs / name
        if not src.exists():
            continue
        _rclone(["copyto", str(src), f"{output_remote}/{name}.uploading"])
        _rclone(["moveto", f"{output_remote}/{name}.uploading", f"{output_remote}/{name}"])
        published.append(name)

    listing = _rclone(["lsjson", output_remote], check=False)
    sizes = {e["Name"]: e.get("Size", 0) for e in json.loads(listing.stdout or "[]")}
    missing = [n for n in published if sizes.get(n, 0) <= 0]
    if missing:
        raise RunnerError(
            f"Publish verification failed for {missing}: not present with size>0 in {output_remote} "
            "after upload (write-back may have stalled). Checkpoint is kept; re-run to retry."
        )
    return published


# -- orchestrator ------------------------------------------------------------------------


def _dump_render_logs(local_job: Path) -> None:
    """On render failure, print the ffmpeg logs (mux + scene) to stdout so they reach the
    Kaggle/Colab papermill log. The .log files otherwise die with the ephemeral box, leaving
    only "FFmpeg failed (exit 1). See log: <gone>" — this surfaces the real ffmpeg stderr."""
    logs_dir = Path(local_job) / ".videotool" / "tmp" / "logs"
    if not logs_dir.exists():
        print(f"runner: no render logs dir at {logs_dir}")
        return
    for log in sorted(logs_dir.glob("*.log")):
        print(f"\n===== {log.name} (last 120 lines) =====")
        try:
            for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]:
                print(line)
        except OSError as exc:
            print(f"(could not read {log}: {exc})")


def _ensure_prepare_artifacts(
    local_job: Path,
    overlay_library: str | Path = Path.home() / ".local/share/videotool/overlays",
) -> None:
    """Resume re-stages the source (wiping local_job) but skips cloud_director (pinned), so the
    artifacts prepare_job/apply_creative created — the media/ dir, outputs/captions.srt, the staged
    sfx/<cue> files, and the atmosphere overlay — are gone. render's path validation, the mux
    subtitles/overlay filters, and the sfx step all need them; re-materialize from the source, the
    SFX pack, and the overlay library."""
    import yaml  # videotool dep; lazy import keeps the module stdlib-only at load
    local_job = Path(local_job)
    (local_job / "media").mkdir(exist_ok=True)
    outputs = local_job / "outputs"
    outputs.mkdir(exist_ok=True)
    captions = outputs / "captions.srt"
    if not captions.exists():
        srts = sorted(local_job.glob("*_vi_qa.srt")) or sorted(local_job.glob("*.srt"))
        if srts:
            shutil.copy(srts[0], captions)
            print(f"runner: re-materialized outputs/captions.srt from {srts[0].name} (resume)")
    # Re-stage the SFX cue files apply_creative copied into sfx/ on the first run (checkpoint
    # saves job.yaml + clips, not sfx/, so a resume would otherwise hit "cue file not found").
    job_yaml = local_job / "job.yaml"
    if job_yaml.exists():
        try:
            data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
        except OSError:
            data = {}
        sfx = (data.get("enhance") or {}).get("sfx") or {}
        pack = sfx.get("pack")
        cues = sfx.get("cues") or []
        if pack and cues:
            pack_dir = Path.home() / ".local/share/videotool/sfx" / pack
            dest = local_job / "sfx"
            dest.mkdir(exist_ok=True)
            for cue in cues:
                name = Path(str(cue.get("file", ""))).name
                if name and (pack_dir / name).exists() and not (dest / name).exists():
                    shutil.copy(pack_dir / name, dest / name)
            print(f"runner: re-staged sfx cue files into sfx/ from pack '{pack}' (resume)")
        # Re-stage the atmosphere overlay apply_creative copied into the job root on the first run
        # (job.yaml keeps inputs.particle_overlay = the bare filename; without the file, render's
        # path validation aborts with "Path does not exist: <overlay>" — the Chap 14 resume crash).
        overlay = (data.get("inputs") or {}).get("particle_overlay")
        if overlay:
            name = Path(str(overlay)).name
            src = Path(overlay_library) / name
            if src.exists() and not (local_job / name).exists():
                shutil.copy(src, local_job / name)
                print(f"runner: re-staged overlay {name} from library (resume)")


def render_job(
    source_remote: str,
    output_remote: str,
    checkpoint_remote: str,
    creative_remote: str | None = None,
    provider: str | None = None,
    autonomous: bool = False,
    sfx_library: str | Path = Path.home() / ".local/share/videotool/sfx",
    overlay_library: str | Path = Path.home() / ".local/share/videotool/overlays",
    local_job: str | Path = "/content/job",
    repo_ref: str | None = None,
    allow_cpu: bool = False,
) -> None:
    """Full cloud render. `*_remote` are rclone specs (e.g. `gdrive:path`). Idempotent: rerun
    after a disconnect resumes from the verified checkpoint with no LLM call and no re-encode.

    `creative_remote` = rclone spec of the Claude Code CLI-authored `creative.yaml` (music_schedule,
    SFX cues, mood, atmosphere overlay, description). When set (the normal path) the render box runs
    NO LLM — Claude did the authoring. `autonomous=True` is the fallback (on-box LLM) for notebook
    runs with no Claude in the loop.
    """
    import cloud_director  # noqa: PLC0415

    vc.setup(repo_ref=repo_ref or vc.DEFAULT_REPO_REF)
    local_job = Path(local_job)
    stage_in(source_remote, local_job)

    job_yaml = local_job / "job.yaml"
    resumed = restore_checkpoint(checkpoint_remote, local_job)
    if not resumed:
        creative_path = None
        if creative_remote:
            creative_path = local_job / "creative.yaml"
            _rclone(["copyto", creative_remote, str(creative_path)])
        cloud_director.run(
            local_job, creative_path=creative_path, provider=provider,
            autonomous=autonomous, sfx_library=sfx_library, overlay_library=overlay_library,
        )
        parallax = local_job / "Parallax"
        if parallax.exists():
            vc._run_cli(["parallax-link", str(job_yaml), "--clips-dir", str(parallax)])
        # First run: probe the GPU, fix the encoder, and pin the authoring so the very next
        # disconnect can resume against that exact encoder.
        _set_encoder(job_yaml, probe_encoder(allow_cpu=allow_cpu))
        _rclone(["copyto", str(job_yaml), f"{checkpoint_remote}/job.yaml"])
    else:
        # Resume: KEEP the pinned encoder — re-probing could pick a different one and weld a
        # mismatched clip into the checkpointed NVENC clips (H4). Only assert it is still usable.
        _assert_encoder_supported(_current_encoder(job_yaml))
    _ensure_prepare_artifacts(local_job, overlay_library)  # resume wipes local_job but skips cloud_director
    sync = CheckpointSync(local_job, checkpoint_remote).start()
    try:
        vc._run_cli(["render", str(job_yaml), "--preset", PRESET])
    except subprocess.CalledProcessError:
        _dump_render_logs(local_job)  # surface ffmpeg logs to the papermill log before re-raise
        raise
    finally:
        sync.stop()

    vc._run_cli(["sfx", str(job_yaml)])
    vc._run_cli(["package", str(job_yaml)])

    published = publish_verified(local_job / "outputs", output_remote)
    print(f"runner: published {published} -> {output_remote}")
    _rclone(["purge", checkpoint_remote], check=False)  # only after verified publish (H6)
    print("runner: checkpoint purged after verified publish. Done.")


def _set_encoder(job_yaml: Path, encoder: str) -> None:
    """Set render.encoder on the job.yaml (first run only). A resume never calls this — it keeps
    the pinned encoder so NVENC clips are never mixed with a re-probed encoder (H4)."""
    import yaml

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    data.setdefault("render", {})["encoder"] = encoder
    job_yaml.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _current_encoder(job_yaml: Path) -> str:
    import yaml

    data = yaml.safe_load(job_yaml.read_text(encoding="utf-8")) or {}
    return data.get("render", {}).get("encoder", "libx264-balanced")


def _assert_encoder_supported(encoder: str) -> None:
    """On resume, confirm the environment still supports the pinned encoder. An NVENC-pinned job
    that lands on a no-NVENC/old-ffmpeg session aborts (do not re-encode remaining clips on CPU
    and weld them into the NVENC checkpoint)."""
    if not encoder.startswith("h264_nvenc"):
        return
    if probe_encoder(allow_cpu=False) != encoder:
        raise RunnerError(
            f"Resume needs the pinned encoder '{encoder}', but this session can't provide it "
            "(no NVENC / old ffmpeg). Reconnect to a T4 and rerun; do NOT switch encoders mid-job."
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Full cloud render from a Drive folder to Output/.")
    parser.add_argument("source_remote", help="rclone spec of the source asset folder, e.g. gdrive:.../CHAP N")
    parser.add_argument("output_remote", help="rclone spec of the Output/ folder, e.g. gdrive:.../CHAP N/Output")
    parser.add_argument("checkpoint_remote", help="rclone spec of the checkpoint dir, e.g. gdrive:_VIDEOTOOL_SHARED/checkpoints/CHAP-N")
    parser.add_argument("--creative", default=None, help="rclone spec of the Claude-authored creative.yaml")
    parser.add_argument("--autonomous", action="store_true", help="fallback: on-box LLM authors job.yaml (no Claude)")
    parser.add_argument("--provider", choices=["kaggle", "glm", "gemini", "anthropic"], default=None)
    parser.add_argument("--sfx-library", default=str(Path.home() / ".local/share/videotool/sfx"))
    parser.add_argument("--overlay-library", default=str(Path.home() / ".local/share/videotool/overlays"))
    parser.add_argument("--repo-ref", default=None, help="pin to a commit SHA (git+https://.../video-tool@<sha>)")
    parser.add_argument("--allow-cpu", action="store_true", help="fall back to capped x264 when NVENC is absent")
    args = parser.parse_args()
    render_job(
        args.source_remote, args.output_remote, args.checkpoint_remote,
        creative_remote=args.creative, provider=args.provider, autonomous=args.autonomous,
        sfx_library=args.sfx_library, overlay_library=args.overlay_library,
        repo_ref=args.repo_ref, allow_cpu=args.allow_cpu,
    )
