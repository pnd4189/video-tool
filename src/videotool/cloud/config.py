"""Shared knobs for the cloud render flow (staging, watching, finishing). Env-overridable."""

from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

KERNELS = {"gpu": "pnd4189/videotool-render", "tpu": "pnd4189/videotool-render-tpu"}
RUNTIMES = ("gpu", "tpu")
CLOUD_MODULES = ("Colab/cloud_director.py", "Colab/cloud_render_runner.py", "Colab/videotool_cloud.py")
GITHUB_REMOTE = "https://github.com/pnd4189/video-tool"


def shared_root() -> str:
    return os.environ.get("VIDEOTOOL_SHARED_ROOT", "gdrive:_VIDEOTOOL_SHARED")


def config_name(runtime: str) -> str:
    return {"gpu": "render_job.json", "tpu": "render_job.tpu.json"}[runtime]


def clip_dir(checkpoint: str) -> str:
    return f"{checkpoint.rstrip('/')}/clips/youtube-16x9"


def _env_seconds(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


POLL_S = _env_seconds("VIDEOTOOL_WATCH_POLL_S", 180.0)
PROGRESS_S = _env_seconds("VIDEOTOOL_PROGRESS_S", 900.0)
REMIND_AFTER_S = _env_seconds("VIDEOTOOL_REMIND_AFTER_S", 3600.0)
ABANDON_AFTER_S = _env_seconds("VIDEOTOOL_ABANDON_AFTER_S", 86400.0)
HERMES_TIMEOUT_S = _env_seconds("VIDEOTOOL_HERMES_TIMEOUT_S", 30.0)
REMOTE_TIMEOUT_S = _env_seconds("VIDEOTOOL_REMOTE_TIMEOUT_S", 300.0)
