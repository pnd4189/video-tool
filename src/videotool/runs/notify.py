"""Notify the user: Telegram via `hermes send`, then `notify-send`, then the state file itself."""

from __future__ import annotations

import time

from videotool.cloud.config import HERMES_TIMEOUT_S
from videotool.cloud.remote import Runner
from videotool.runs import state as run_state



def _hermes(runner: Runner, message: str) -> bool:
    code, _ = runner(
        ["hermes", "send", "--to", "telegram", "--subject", "[videotool]", "-q", message],
        timeout=HERMES_TIMEOUT_S,
    )
    return code == 0


def _notify_send(runner: Runner, message: str) -> bool:
    code, _ = runner(["notify-send", "[videotool]", message], timeout=15)
    return code == 0


def send(runner: Runner, message: str) -> tuple[bool, str]:
    """Try Telegram, then the desktop, then nothing. Returns (delivered, channel)."""
    if _hermes(runner, message):
        return True, "telegram"
    if _notify_send(runner, message):
        return True, "notify-send"
    return False, "none"


def notify(runner: Runner, state: dict, event: str, message: str) -> None:
    """Send once per event name; an undeliverable message is recorded, never raised."""
    if run_state.already_notified(state, event):
        return
    try:
        delivered, channel = send(runner, message)
    except Exception:  # noqa: BLE001 — a broken notifier must never break the watcher
        delivered, channel = False, "none"
    run_state.record_event(state, event, message)
    if not delivered:
        undelivered = state.get("undelivered") or []
        undelivered.append({"at": time.time(), "message": message})
        state["undelivered"] = undelivered[-10:]
    state["last_channel"] = channel
    run_state.save(state)
