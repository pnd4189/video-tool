from __future__ import annotations

import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from videotool.core.errors import DependencyError, RenderError
from videotool.render.commands import CommandPlan

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
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                plan.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise DependencyError("ffmpeg was not found. Install FFmpeg 6.1+ and retry.") from exc

        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write("$ " + " ".join(plan.command) + "\n\n")
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
                    f"FFmpeg timed out after {self.timeout_seconds}s for {plan.preset}. See log: {log_path}"
                ) from None
            except KeyboardInterrupt:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise

        if return_code != 0:
            raise RenderError(f"FFmpeg failed for {plan.preset} (exit {return_code}). See log: {log_path}")
        return RenderResult(plan.output_path, plan.preset, time.monotonic() - started, log_path)
