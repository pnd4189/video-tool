"""Guarded cleanup after a verified publish: delete this run's config file on Drive.

The config must survive a failure (it is the resume handle), and must never be deleted while
another render — maybe from another session — is using it. Three conditions, all checked at
finish time: the verify passed, the kernel is idle, and the config on Drive still points at
THIS slug.
"""

from __future__ import annotations

import json
from videotool.cloud import remote
from videotool.cloud.config import REMOTE_TIMEOUT_S
from videotool.cloud.remote import Runner


class RefuseCleanup(RuntimeError):
    """Cleanup refused — carrying the reason is the whole point."""


def finish(runner: Runner, state: dict, shared: str) -> None:
    """Raise RefuseCleanup instead of deleting when any guard trips."""
    if state.get("status") != "done":
        raise RefuseCleanup(f"trạng thái {state.get('status')} — chỉ dọn sau khi verify ĐẠT")
    status = remote.kernel_status(runner, state["kernel"])
    if status is None:
        raise RefuseCleanup(f"không đọc được trạng thái kernel {state['kernel']} — không dọn config")
    if status in ("queued", "running"):
        raise RefuseCleanup(f"kernel {state['kernel']} đang {status} — không dọn config")
    if not state.get("config_name"):
        raise RefuseCleanup("state không có config_name — không biết file nào để dọn")
    config_remote = f"{shared}/{state['config_name']}"
    current = _read_config(runner, config_remote)
    if current is None:
        return  # already gone — nothing to do
    if not _points_at(current, state["slug"]):
        raise RefuseCleanup(f"{state['config_name']} đã trỏ tập khác — không đụng")
    remote.delete_remote_file(runner, config_remote)


def _read_config(runner: Runner, config_remote: str) -> dict | None:
    try:
        return json.loads(remote.remote_text(runner, config_remote, REMOTE_TIMEOUT_S) or "null")
    except (remote.RemoteError, ValueError):
        return None


def _points_at(config: dict, slug: str) -> bool:
    return str(config.get("checkpoint", "")).rstrip("/").endswith(f"/{slug}") or \
        str(config.get("creative", "")).rstrip("/").endswith(f"/{slug}.yaml")
