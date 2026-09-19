"""Every external call (rclone/kaggle/git) behind one injectable runner, list-form only.

`runner(args, timeout, env) -> (returncode, stdout: bytes)` — bytes because `rclone cat --head`
carries binary headers (mvhd/RIFF); text call sites decode via `_run`. Tests pass a fake.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from videotool.cloud.config import GITHUB_REMOTE

Runner = Callable[..., tuple[int, bytes]]

_KAGGLE_STATES = {
    "QUEUED": "queued", "RUNNING": "running", "COMPLETE": "complete",
    "ERROR": "error", "CANCELLED": "cancelled", "CANCELREQUESTED": "cancelled",
}


class RemoteError(RuntimeError):
    """A remote call failed (network, quota, rclone/kaggle exit)."""


def real_runner(args: list[str], timeout: float = 120, env: dict | None = None) -> tuple[int, bytes]:
    result = subprocess.run(
        args, capture_output=True, timeout=timeout, check=False,
        env={**os.environ, **(env or {})},
    )
    return result.returncode, result.stdout


def _run(runner: Runner, args: list[str], timeout: float) -> str:
    code, out = runner(list(args), timeout=timeout)
    if code != 0:
        raise RemoteError(f"{' '.join(args[:3])}… exited {code}")
    return out.decode("utf-8", errors="replace") if isinstance(out, bytes) else out


def rclone_text(runner: Runner, args: list[str], timeout: float = 300) -> str:
    return _run(runner, ["rclone", *args], timeout)


def kaggle_text(runner: Runner, args: list[str], timeout: float = 120) -> str:
    return _run(runner, ["kaggle", *args], timeout)


def kernel_status(runner: Runner, kernel: str) -> str | None:
    """queued|running|complete|error|cancelled, or None when the CLI output is not parsable."""
    try:
        out = kaggle_text(runner, ["kernels", "status", kernel])
    except (RemoteError, subprocess.TimeoutExpired):
        return None
    m = re.search(r'KernelWorkerStatus\.([A-Z]+)"', out)
    return _KAGGLE_STATES.get(m.group(1)) if m else None


def remote_text(runner: Runner, remote: str, timeout: float = 300) -> str:
    return rclone_text(runner, ["cat", remote], timeout)


def remote_head(runner: Runner, remote: str, nbytes: int, timeout: float = 300) -> bytes:
    code, out = runner(["rclone", "cat", "--head", str(nbytes), remote], timeout=timeout)
    if code != 0:
        raise RemoteError(f"rclone cat --head {remote} exited {code}")
    return out if isinstance(out, bytes) else out.encode("latin-1")


def remote_exists(runner: Runner, remote: str) -> bool:
    code, _ = runner(["rclone", "lsf", remote], timeout=60)
    return code == 0


def write_remote_file(runner: Runner, local: Path, remote: str) -> None:
    rclone_text(runner, ["copyto", str(local), remote])


def delete_remote_file(runner: Runner, remote: str) -> None:
    rclone_text(runner, ["delete", remote])


def md5_of_blob(runner: Runner, git_path: str) -> str:
    code, out = runner(["git", "-C", str(Path(__file__).resolve().parents[3]),
                        "show", f"origin/main:{git_path}"], 60)
    if code != 0:
        raise RemoteError(f"git show origin/main:{git_path} exited {code}")
    return hashlib.md5(out).hexdigest()


def md5_on_remote(runner: Runner, remote: str) -> str | None:
    """`rclone md5sum` of one Drive file; None when the file is absent or has no hash yet."""
    code, out = runner(["rclone", "md5sum", remote], timeout=120)
    if code != 0:
        return None
    m = re.match(r"([0-9a-f]{32})\s", out.decode("utf-8", errors="replace"))
    return m.group(1) if m and not m.group(1).startswith("0" * 32) else None


def github_head(runner: Runner) -> str | None:
    try:
        return _run(runner, ["git", "ls-remote", GITHUB_REMOTE, "main"], 60).split()[0]
    except (RemoteError, IndexError):
        return None


def local_origin_main(runner: Runner) -> str | None:
    try:
        return _run(runner, ["git", "-C", str(Path(__file__).resolve().parents[3]),
                             "rev-parse", "origin/main"], 30).strip() or None
    except RemoteError:
        return None


def count_clips(runner: Runner, checkpoint: str) -> int:
    from videotool.cloud.config import clip_dir

    code, out = runner(["rclone", "lsf", clip_dir(checkpoint)], timeout=120)
    if code != 0:
        return -1  # the folder does not exist yet — no clips, not an error
    names = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else out
    return sum(1 for name in names.splitlines() if re.fullmatch(r"scene-\d{4}\.mp4", name.strip()))


def download_kernel_log(runner: Runner, kernel: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    kaggle_text(runner, ["kernels", "output", kernel, "-p", str(dest)], timeout=600)
    return dest
