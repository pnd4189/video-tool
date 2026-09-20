"""`videotool renders hook` — surface render status inside each CLI session.

start = everything active + finished within 24h (+ a warning when the watcher daemon is down).
prompt = only what changed since this CLI last saw the renders (a per-CLI seen marker).
Output format per CLI; never raises, never exceeds a few lines, always exits 0.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from videotool.cloud.remote import Runner
from videotool.runs import state as run_state

DAEMON_UNIT = "videotool-watchd.service"


def _daemon_running(runner: Runner) -> bool:
    code, out = runner(["systemctl", "--user", "is-active", DAEMON_UNIT], timeout=10)
    text = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else out
    return code == 0 and text.strip() == "active"


def _summary(states: list[dict]) -> str:
    return "\n".join(run_state.summary_line(s) for s in states) if states else ""


def protected_changes(runner: Runner) -> list[str]:
    """Uncommitted changes outside `plans/` — what a render-only agent must never have touched."""
    from videotool.agent.guard import REPO_ROOT, WRITABLE_IN_REPO

    code, out = runner(["git", "-C", str(REPO_ROOT), "status", "--porcelain"], timeout=15)
    if code != 0:
        return []
    text = out.decode("utf-8", errors="replace") if isinstance(out, bytes) else out
    paths = []
    for line in text.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path and not path.startswith(tuple(f"{d}/" for d in WRITABLE_IN_REPO)):
            paths.append(path)
    return paths


def start_context(runner: Runner, cli: str = "claude") -> str:
    """The session opener. The inbox count and the protected-file warning are Claude's detection
    net — a render-only agent gets only the render status."""
    from videotool.agent.lessons import pending

    active = run_state.list_states(days=30.0, statuses=run_state.ACTIVE)
    recent = run_state.list_states(days=1.0, statuses=run_state.TERMINAL)
    lines = []
    if active:
        lines.append("[videotool] đang chạy:")
        lines.append(_summary(active))
    if recent:
        lines.append("[videotool] 24h qua:")
        lines.append(_summary(recent))
    if active and not _daemon_running(runner):
        lines.append(f"[videotool] CẢNH BÁO: {DAEMON_UNIT} không chạy — không ai canh/báo các tập trên.")
    if cli != "claude":
        return "\n".join(lines)
    waiting = pending()
    if waiting:
        lines.append(f"[videotool] {waiting} bài học trong lessons-inbox.md chờ xác minh.")
    touched = protected_changes(runner)
    if touched:
        lines.append(f"[videotool] {len(touched)} file code/workflow đang sửa chưa commit: "
                     + ", ".join(touched[:5]) + ("…" if len(touched) > 5 else ""))
    return "\n".join(lines)


def _known_states() -> list[dict]:
    return run_state.list_states(days=7.0, statuses=run_state.ACTIVE + run_state.TERMINAL)


def _load_seen(cli: str) -> dict:
    try:
        return json.loads((run_state.state_dir() / f".seen-{cli}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_seen(cli: str, seen: dict) -> None:
    try:
        run_state.ensure_dir()
        (run_state.state_dir() / f".seen-{cli}.json").write_text(json.dumps(seen), encoding="utf-8")
    except OSError:
        pass


def _mark(st: dict) -> dict:
    return {"at": float(st.get("updated_at") or time.time()), "status": st.get("status")}


def _is_news(st: dict, mark: dict | float | int | None) -> bool:
    """A status move is news whenever it happened; a same-status update needs a real time gap.

    Comparing times alone hid a fast transition (verifying -> done lands within the same second)."""
    if mark is None:
        return True
    if isinstance(mark, (int, float)):  # marker written before statuses were recorded
        mark = {"at": float(mark), "status": None}
    return st.get("status") != mark.get("status") or \
        float(st.get("updated_at") or 0) > float(mark.get("at") or 0) + 1.0


def mark_seen(cli: str, states: list[dict]) -> None:
    """Record these states as already shown, so the next prompt hook only reports what moved."""
    seen = _load_seen(cli)
    seen.update({st["slug"]: _mark(st) for st in states})
    _save_seen(cli, seen)


def prompt_context(cli: str) -> str:
    """Changes since the last time this CLI looked: new renders or any status move."""
    seen = _load_seen(cli)
    changed = []
    for st in _known_states():
        if _is_news(st, seen.get(st["slug"])):
            changed.append(st)
            seen[st["slug"]] = _mark(st)
    if not changed:
        return ""
    _save_seen(cli, seen)
    return "[videotool] cập nhật render:\n" + _summary(changed)


def choose_event(cli: str, payload: str) -> str:
    """`auto` for agy: the first invocation of a session is a start, later ones a prompt.

    `invocationNum` counts from 0 — captured from a real agy PreInvocation payload, 2026-09-20."""
    if cli != "agy" or not payload:
        return "prompt"
    try:
        data = json.loads(payload)
    except ValueError:
        return "prompt"
    return "start" if int(data.get("invocationNum", -1)) == 0 else "prompt"


def hook_output(cli: str, event: str, payload: str, runner: Runner) -> str:
    """The exact stdout for the CLI's hook config; empty string when there is nothing to say."""
    event = event if event != "auto" else choose_event(cli, payload)
    if event == "start":
        text = start_context(runner, cli).strip()
        mark_seen(cli, _known_states())  # the first prompt hook must not repeat the session opener
    else:
        text = prompt_context(cli).strip()
    if not text:
        return ""
    if cli == "agy":
        return json.dumps({"injectSteps": [{"ephemeralMessage": text}]}, ensure_ascii=False)
    # Claude Code ignores hookSpecificOutput without the event name (verified against the hooks
    # already running on this machine).
    name = "SessionStart" if event == "start" else "UserPromptSubmit"
    return json.dumps({"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}},
                      ensure_ascii=False)


def install_service(runner: Runner, venv_bin: Path) -> Path:
    """Write the systemd user unit and enable it (Linger keeps it alive without a login session)."""
    unit = Path.home() / ".config/systemd/user/videotool-watchd.service"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(
        "[Unit]\n"
        "Description=videotool Kaggle render watcher (no LLM)\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        f"ExecStart={venv_bin} cloud watchd\n"
        "Restart=on-failure\n"
        "RestartSec=30\n\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    runner(["systemctl", "--user", "daemon-reload"], timeout=30)
    code, _ = runner(["systemctl", "--user", "enable", "--now", DAEMON_UNIT], timeout=60)
    if code != 0:
        raise RuntimeError(f"systemctl enable --now {DAEMON_UNIT} thất bại (exit {code})")
    return unit


def main(argv: list[str] | None = None) -> int:
    """Lightweight entry point for CLI hooks: `python -m videotool.runs.hook --cli agy --event auto`.

    Skips the full `videotool` CLI import (pydantic + render modules, ~140ms) so a hook stays well
    under 100ms. `--payload -` reads the hook payload from stdin. Always returns 0."""
    import argparse
    import subprocess
    import sys

    parser = argparse.ArgumentParser(prog="videotool-hook")
    parser.add_argument("--cli", required=True, choices=("claude", "codex", "agy"))
    parser.add_argument("--event", default="prompt", choices=("start", "prompt", "auto"))
    parser.add_argument("--payload", default="")
    try:
        args = parser.parse_args(argv)
        payload = sys.stdin.read() if args.payload == "-" else args.payload

        def runner(cmd: list[str], timeout: float = 10, env: dict | None = None) -> tuple[int, bytes]:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
            return result.returncode, result.stdout

        out = hook_output(args.cli, args.event, payload, runner)
        if out:
            print(out)
    except BaseException:  # noqa: BLE001 — a hook must never break a session
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
