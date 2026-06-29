from __future__ import annotations

import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError
from videotool.render.commands import CommandPlan
from videotool.render.segmented import SegmentedPlan

DEFAULT_TIMEOUT_SECONDS = 60 * 60 * 6  # 6h ceiling per render; tune if you ever do longer videos.


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
        for index, scene in enumerate(plan.scene_commands):
            if _is_complete(scene.output_path):
                continue
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
        plan.concat_list_path.parent.mkdir(parents=True, exist_ok=True)
        plan.concat_list_path.write_text(plan.concat_list_text, encoding="utf-8")
        plan.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(plan.mux_command, logs_dir / f"{plan.preset}-mux.log", plan.preset)
        return RenderResult(plan.output_path, plan.preset, time.monotonic() - started, logs_dir)

    def _run(self, command: list[str], log_path: Path, preset: str) -> float:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
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


def _is_complete(clip_path: Path) -> bool:
    return clip_path.exists() and clip_path.stat().st_size > 0
