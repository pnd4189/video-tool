"""`videotool cloud`: stage, watchd (daemon), finish."""

from __future__ import annotations

from pathlib import Path

import typer

cloud_app = typer.Typer(no_args_is_help=True, help="Stage and watch Kaggle renders without an agent.")


@cloud_app.command()
def stage(
    source: str = typer.Argument(..., help="Episode folder, rclone spec (gdrive:… / gdrive,root_folder_id=…:)."),
    creative: Path = typer.Option(..., "--creative", exists=True, dir_okay=False),
    runtime: str = typer.Option("tpu", "--runtime", help="gpu | tpu"),
    slug: str | None = typer.Option(None, "--slug"),
    scene_workers: int | None = typer.Option(None, "--scene-workers"),
    resume: bool = typer.Option(False, "--resume", help="Continue the pinned job.yaml already in this slug's checkpoint."),
    fresh: bool = typer.Option(False, "--fresh", help="Delete this slug's own checkpoint first so the new creative is used."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    template: Path | None = typer.Option(None, "--template", exists=True, dir_okay=False,
                                         help="Description template to stage into the source folder."),
) -> None:
    """Lint the creative, check every guard, upload creative+config, and mark the run staged."""
    from videotool.cloud.stage import stage as run_stage

    raise typer.Exit(run_stage(source, creative, runtime, slug, scene_workers, resume, dry_run, template,
                               fresh=fresh))


@cloud_app.command()
def watchd(
    once: bool = typer.Option(False, "--once", help="One poll cycle, then exit (testing)."),
) -> None:
    """The watcher daemon body — normally run by videotool-watchd.service, not by hand."""
    from videotool.cloud.watch import loop

    loop(once=once)


@cloud_app.command()
def finish(slug: str = typer.Argument(...)) -> None:
    """Delete this run's config on Drive — only after a verified publish, kernel idle, config still ours."""
    from videotool.cloud.config import shared_root
    from videotool.cloud.finish import RefuseCleanup, finish as run_finish
    from videotool.cloud.remote import real_runner
    from videotool.runs import state as run_state

    st = run_state.load(slug)
    if st is None:
        typer.echo(f"không có state cho slug {slug}", err=True)
        raise typer.Exit(2)
    try:
        run_finish(real_runner, st, shared_root())
        typer.echo(f"đã dọn config của {slug}")
    except RefuseCleanup as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
