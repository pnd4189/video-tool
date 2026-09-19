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


def start_context(runner: Runner) -> str:
    active = run_state.list_states(days=30.0, statuses=run_state.ACTIVE)
    recent = [s for s in run_state.list_states(days=1.0, statuses=run_state.TERMINAL)
              if s not in active]
    lines = []
    if active:
        lines.append("[videotool] đang chạy:")
        lines.append(_summary(active))
    if recent:
        lines.append("[videotool] 24h qua:")
        lines.append(_summary(recent))
    if active and not _daemon_running(runner):
        lines.append(f"[videotool] CẢNH BÁO: {DAEMON_UNIT} không chạy — không ai canh/báo các tập trên.")
    return "\n".join(lines)


def prompt_context(cli: str) -> str:
    """Changes since the last time this CLI looked: new renders or any status move."""
    marker = run_state.state_dir() / f".seen-{cli}.json"
    try:
        seen = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    changed = []
    now = time.time()
    for st in run_state.list_states(days=7.0, statuses=run_state.ACTIVE + run_state.TERMINAL):
        if st.get("updated_at", 0) > float(seen.get(st["slug"], 0)) + 1.0:
            changed.append(st)
            seen[st["slug"]] = st.get("updated_at", now)
    if not changed:
        return ""
    try:
        run_state.ensure_dir()
        marker.write_text(json.dumps(seen), encoding="utf-8")
    except OSError:
        pass
    return "[videotool] cập nhật render:\n" + _summary(changed)


def choose_event(cli: str, payload: str) -> str:
    """`auto` for agy: the first invocation of a session is a start, later ones a prompt."""
    if cli != "agy" or not payload:
        return "prompt"
    try:
        data = json.loads(payload)
    except ValueError:
        return "prompt"
    return "start" if int(data.get("invocationNum", 0)) == 1 else "prompt"


def hook_output(cli: str, event: str, payload: str, runner: Runner) -> str:
    """The exact stdout for the CLI's hook config; empty string when there is nothing to say."""
    event = event if event != "auto" else choose_event(cli, payload)
    text = (start_context(runner) if event == "start" else prompt_context(cli)).strip()
    if not text:
        return ""
    if cli == "agy":
        return json.dumps({"injectSteps": [{"ephemeralMessage": text}]}, ensure_ascii=False)
    return json.dumps({"hookSpecificOutput": {"additionalContext": text}}, ensure_ascii=False)


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
