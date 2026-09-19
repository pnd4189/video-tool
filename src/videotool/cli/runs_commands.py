"""`videotool renders`: list runs, the CLI hook, daemon install, a test ping."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from videotool.runs import state as run_state

renders_app = typer.Typer(help="Render runs: status, hooks, watcher daemon.")


@renders_app.callback(invoke_without_command=True)
def default(ctx: typer.Context) -> None:
    """Bare `videotool renders` = the table of active runs and runs finished in the last 7 days."""
    if ctx.invoked_subcommand is None:
        list_runs(days=7.0)


@renders_app.command("list-runs")
def list_runs(days: float = typer.Option(7.0, "--days")) -> None:
    """Active renders plus everything finished within --days."""
    active = run_state.list_states(days=30.0, statuses=run_state.ACTIVE)
    rest = [s for s in run_state.list_states(days=days, statuses=run_state.TERMINAL)
            if s not in active]
    for group, states in (("đang chạy", active), ("kết thúc", rest)):
        if states:
            typer.echo(f"[{group}]")
        for st in states:
            typer.echo(f"  {run_state.summary_line(st)}")
    if not active and not rest:
        typer.echo("không có render nào gần đây")


@renders_app.command()
def hook(
    cli: str = typer.Option(..., "--cli", help="claude | codex | agy"),
    event: str = typer.Option("prompt", "--event", help="start | prompt | auto"),
    payload: str = typer.Option("", "--payload", help="The hook's JSON payload (agy PreInvocation)."),
) -> None:
    """Context for a CLI session hook. Prints nothing when there is no news; always exits 0."""
    from videotool.cloud.remote import real_runner
    from videotool.runs.hook import hook_output

    try:
        out = hook_output(cli, event, payload, real_runner)
    except Exception:  # noqa: BLE001 — a hook must never break a session
        raise typer.Exit(0)
    if out:
        typer.echo(out)
    raise typer.Exit(0)


@renders_app.command("install-daemon")
def install_daemon() -> None:
    """Write ~/.config/systemd/user/videotool-watchd.service and enable it now."""
    from videotool.cloud.remote import real_runner
    from videotool.runs.hook import install_service

    venv_bin = Path(__file__).resolve().parents[3] / ".venv/bin/videotool"
    try:
        unit = install_service(real_runner, venv_bin)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"lỗi: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"đã ghi {unit} và bật videotool-watchd")


@renders_app.command("test-notify")
def test_notify() -> None:
    """One Telegram ping through the real delivery chain."""
    from videotool.cloud.remote import real_runner
    from videotool.runs.notify import send

    delivered, channel = send(real_runner,
                              "tin thử từ videotool-watchd — nếu bạn thấy dòng này, kênh báo hoạt động.")
    typer.echo(f"delivered={delivered} channel={channel}")
    raise typer.Exit(0 if delivered else 1)


@renders_app.command()
def status(slug: str = typer.Argument(...)) -> None:
    """Print one render's full state file (JSON)."""
    st = run_state.load(slug)
    if st is None:
        typer.echo(f"không có state cho slug {slug}", err=True)
        raise typer.Exit(2)
    typer.echo(json.dumps(st, ensure_ascii=False, indent=1))
