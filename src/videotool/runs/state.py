"""Render state files: `~/.local/state/videotool/renders/<slug>.json`, written atomically."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

ACTIVE = ("staged", "queued", "running", "verifying", "watch-error")
TERMINAL = ("done", "failed", "abandoned")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "videotool" / "renders"


def path_for(slug: str) -> Path:
    return state_dir() / f"{slug}.json"


def ensure_dir() -> Path:
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    return folder


def load(slug: str) -> dict | None:
    """The state dict, or None when missing/corrupt (a broken file must never crash a watcher)."""
    try:
        data = json.loads(path_for(slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("slug") == slug else None


def save(state: dict) -> None:
    state["updated_at"] = time.time()
    path = path_for(state["slug"])
    ensure_dir()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def new(slug: str, **fields) -> dict:
    return {"slug": slug, "status": "staged", "history": [], "failures": 0, **fields}


def transition(state: dict, status: str, note: str = "") -> bool:
    """Record a status change; returns False when it is not a change (idempotent steps)."""
    if state.get("status") == status:
        return False
    state.setdefault("history", []).append(
        {"at": time.time(), "from": state.get("status"), "to": status, "note": note})
    state["status"] = status
    state["failures"] = 0
    return True


def record_event(state: dict, event: str, detail: str = "") -> None:
    """The last thing the user was notified about — a restart must not repeat it."""
    state["last_event"] = {"event": event, "at": time.time(), "detail": detail}


def already_notified(state: dict, event: str) -> bool:
    return (state.get("last_event") or {}).get("event") == event


def list_states(days: float = 7.0, statuses: tuple[str, ...] = ACTIVE) -> list[dict]:
    """Active renders (or any statuses) updated within `days`; corrupt files skipped silently."""
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    folder = state_dir()
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("status") in statuses and data.get("updated_at", 0) >= cutoff:
            out.append(data)
    return out


def summary_line(state: dict) -> str:
    """One Vietnamese line for hooks/notifications, no paths that carry secrets."""
    name = state.get("slug", "?")
    if state.get("title"):
        name = f"{name} ({state['title']})"
    bits = [f"{name}: {state.get('status', '?')}"]
    progress = state.get("progress") or {}
    if progress.get("clips", 0) > 0:
        bits.append(f"{progress['clips']} clip")
    verify = state.get("verify") or {}
    if verify.get("ok") is False:
        bits.append("verify lỗi")
    for key in ("error", "note"):
        if state.get(key):
            bits.append(str(state[key])[:120])
    return " — ".join(bits)
