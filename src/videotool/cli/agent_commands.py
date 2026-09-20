"""`videotool agent`: the PreToolUse guard and the lessons inbox for render-only agents."""

from __future__ import annotations

import typer

agent_app = typer.Typer(no_args_is_help=True, help="Guard and lessons inbox for render-only agents.")


@agent_app.command()
def guard(
    cli: str = typer.Option("agy", "--cli", help="Which CLI's hook is calling (agy today)."),
) -> None:
    """Decide one PreToolUse call from stdin. Prints one JSON line and always exits 0.

    An internal failure asks the user instead of allowing: running freely is only safe while the
    guard still works."""
    from videotool.agent.guard import main

    raise typer.Exit(main())


@agent_app.command()
def lesson(
    text: str = typer.Argument(..., help="What happened / evidence / suggested rule."),
    episode: str | None = typer.Option(None, "--episode", help="Episode slug, e.g. binh-thien-chap55."),
    cli: str = typer.Option("agy", "--cli"),
) -> None:
    """Append a lesson to the inbox and tell the user it is waiting for verification."""
    from videotool.agent.lessons import INBOX, append, pending
    from videotool.cloud.remote import real_runner
    from videotool.runs.notify import send

    try:
        written = append(text, episode, cli)
    except (ValueError, FileNotFoundError, OSError) as exc:
        typer.echo(f"không ghi được bài học: {exc}", err=True)
        raise typer.Exit(1) from exc
    first = next((ln.lstrip("- ") for ln in written.splitlines() if ln.startswith("-")), text)
    delivered, channel = send(real_runner, f"Bài học mới từ {cli} chờ Claude xác minh: {first[:200]}")
    typer.echo(f"đã ghi vào {INBOX.name} ({pending()} bài học đang chờ) · tin: {channel}"
               + ("" if delivered else " (chưa gửi được — nói lại với user trong phiên)"))
