"""Pull the first real error lines out of a failed Kaggle kernel's log.

`kaggle kernels output <kernel>` saves `<kernel-slug>.log` (`videotool-render.log`,
`videotool-render-tpu.log`, …): a JSON array of `{stream_name, time, data}` chunks, papermill's
record of the notebook's stdout/stderr. The runner dumps the ffmpeg mux/scene logs into stdout on
failure (`===== *-mux.log =====`), so the real cause is usually in there.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from videotool.cloud import remote
from videotool.cloud.remote import Runner

PATTERNS = (r"RuntimeError", r"RunnerError", r"DirectorError", r"ERROR:", r"Error:",
            r"exited \d+", r"Conversion failed", r"==== .*\.log")
MAX_LINES = 3


def log_text(raw: str) -> str:
    """The notebook's output as plain text; falls back to the raw file when it is not JSON."""
    try:
        chunks = json.loads(raw)
    except ValueError:
        return raw
    if not isinstance(chunks, list):
        return raw
    return "".join(str(c.get("data", "")) for c in chunks if isinstance(c, dict))


def error_lines(text: str) -> list[str]:
    """Up to three lines that look like the real failure, in order; the last line otherwise."""
    picked: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and any(re.search(p, stripped) for p in PATTERNS) and stripped[:200] not in picked:
            picked.append(stripped[:200])
        if len(picked) >= MAX_LINES:
            break
    if picked:
        return picked
    tail = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [tail[-1][:200]] if tail else ["(log rỗng)"]


def kernel_error_lines(runner: Runner, kernel: str) -> list[str]:
    """Download the kernel output and return its error lines; never raises."""
    try:
        with tempfile.TemporaryDirectory(prefix="videotool-kernel-log-") as tmp:
            remote.download_kernel_log(runner, kernel, Path(tmp))
            # The kernel's own log first: an episode's ffmpeg logs can land beside it and sort earlier.
            wanted = f"{kernel.rsplit('/', 1)[-1]}.log"
            logs = sorted(Path(tmp).glob("*.log"), key=lambda p: (p.name != wanted, p.name))
            if not logs:
                return ["(kernel không trả log)"]
            return error_lines(log_text(logs[0].read_text(encoding="utf-8", errors="replace")))
    except (remote.RemoteError, OSError, TimeoutError):
        return ["(không tải được log kernel)"]
