from __future__ import annotations

import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError
from videotool.core.media_probe import probe_media
from videotool.render.commands import CommandPlan
from videotool.render.segmented import SegmentedPlan

DEFAULT_TIMEOUT_SECONDS = 60 * 60 * 6  # 6h ceiling per render; tune if you ever do longer videos.
# Scene clips are independent files, so they render concurrently. The work is filter-bound
# (scale/zoompan, plus the atmosphere blend when it is baked per scene), so one worker per
# core is the right shape — each ffmpeg then gets roughly one core to itself.
MAX_SCENE_WORKERS = 8
# Per-clip frame rounding leaves each scene a fraction of a frame short of its allocated
# duration. Reconcile only when the accumulated shortfall exceeds this (half a second) so a
# clean render is never re-touched, and cap the correction so a pathological probe never
# stretches a clip absurdly.
RECONCILE_TOLERANCE_SECONDS = 0.5
RECONCILE_MAX_SECONDS = 30.0


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    preset: str
    elapsed_seconds: float
    log_path: Path


class RenderExecutor:
    def __init__(self, timeout_seconds: float | None = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, plan: CommandPlan, log_path: Path) -> RenderResult:
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        elapsed = self._run(plan.command, log_path, plan.preset)
        return RenderResult(plan.output_path, plan.preset, elapsed, log_path)

    def run_segmented(self, plan: SegmentedPlan, logs_dir: Path) -> RenderResult:
        """Render each scene clip (skipping clips already on disk), join via the
        concat demuxer, and mux audio. Resumable: a crash mid-run resumes from the
        first missing clip instead of restarting from scene 1."""
        logs_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        pending = [
            (index, scene)
            for index, scene in enumerate(plan.scene_commands)
            if not _is_complete(scene.output_path)
        ]
        if pending:
            workers = min(scene_workers(), len(pending))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                # list() re-raises the first failure; the pool then drains before we move on.
                list(pool.map(lambda item: self._run_scene(item[0], item[1], plan, logs_dir), pending))
        # Reconcile the concatenated scene block to its design duration before the mux: frame
        # rounding shortens every clip a hair, and across hundreds of scenes that adds up to
        # enough for `-shortest` to slice the outro CTA off the end. Re-renders the last
        # narration clip with the deficit added back so video matches audio exactly.
        self._reconcile_scene_block(plan, logs_dir)
        plan.concat_list_path.parent.mkdir(parents=True, exist_ok=True)
        plan.concat_list_path.write_text(plan.concat_list_text, encoding="utf-8")
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(plan.mux_command, logs_dir / f"{plan.preset}-mux.log", plan.preset)
        return RenderResult(plan.output_path, plan.preset, time.monotonic() - started, logs_dir)

    def _run_scene(self, index: int, scene: CommandPlan, plan: SegmentedPlan, logs_dir: Path) -> None:
        scene.output_path.parent.mkdir(parents=True, exist_ok=True)
        # Render to a sibling .part.<ext> file and rename on success. A clip only appears
        # at its final path once ffmpeg exited 0, so an interrupted run (timeout/kill) leaves
        # a .part — never a truncated clip a resumed run would trust via size>0. The temp
        # keeps the real extension: ffmpeg selects the muxer from the output suffix, and a
        # bare ".part" has no recognized container, so the muxer fails to initialize.
        partial = scene.output_path.with_name(
            scene.output_path.stem + ".part" + scene.output_path.suffix
        )
        partial.unlink(missing_ok=True)
        # _build_scene_clip puts the output path last; retarget it to the .part temp.
        command = [*scene.command[:-1], str(partial)]
        self._run(command, logs_dir / f"{plan.preset}-scene-{index:04}.log", plan.preset)
        partial.replace(scene.output_path)

    def _reconcile_scene_block(self, plan: SegmentedPlan, logs_dir: Path) -> None:
        """Re-render the nominated scene clip so the concatenated clips total the design
        duration. The deficit comes from per-clip frame rounding; left uncorrected it makes
        the video shorter than the composed audio and ``-shortest`` cuts the outro CTA.

        This is a safety net over an otherwise-complete render, so any failure to measure the
        clips (a corrupt clip, a transient ffprobe error) skips the correction rather than
        aborting — the mux then surfaces the real problem, if any."""
        spec = plan.reconcile
        if spec is None or not plan.scene_commands:
            return
        complete = [cmd for cmd in plan.scene_commands if _is_complete(cmd.output_path)]
        if len(complete) != len(plan.scene_commands):
            return  # A missing clip means the render failed above; nothing to reconcile.
        try:
            measured = sum(probe_media(cmd.output_path).duration for cmd in complete)
        except Exception:
            return  # Unreadable clip: let the mux report it instead of failing here.
        delta = plan.scenes_total_duration - measured
        if abs(delta) <= RECONCILE_TOLERANCE_SECONDS:
            return
        delta = max(min(delta, RECONCILE_MAX_SECONDS), -RECONCILE_MAX_SECONDS)
        new_duration = spec.scene.duration + delta
        if new_duration < 0.2:
            return
        self._run_scene(spec.index, spec.clip_command(new_duration), plan, logs_dir)

    def _run(self, command: list[str], log_path: Path, preset: str) -> float:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc

        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write("$ " + " ".join(command) + "\n\n")
            try:
                # Stream lines to disk so multi-GB renders don't buffer in memory.
                assert process.stdout is not None
                for line in process.stdout:
                    log_file.write(line)
                return_code = process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise RenderError(
                    f"FFmpeg timed out after {self.timeout_seconds}s for {preset}. See log: {log_path}"
                ) from None
            except KeyboardInterrupt:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise

        if return_code != 0:
            raise RenderError(f"FFmpeg failed for {preset} (exit {return_code}). See log: {log_path}")
        return time.monotonic() - started


def scene_workers() -> int:
    """How many scene clips to render at once. `VIDEOTOOL_SCENE_WORKERS` overrides the
    one-per-core default for boxes where ffmpeg competes with something else."""
    override = os.environ.get("VIDEOTOOL_SCENE_WORKERS", "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return max(1, min(MAX_SCENE_WORKERS, os.cpu_count() or 1))


def _is_complete(clip_path: Path) -> bool:
    return clip_path.exists() and clip_path.stat().st_size > 0
