"""`videotool prepare` and the `videotool creative` group (lint, sfx-pin)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import typer
import yaml

from videotool.creative.rules import CreativeError

creative_app = typer.Typer(no_args_is_help=True, help="Check and pin an episode's creative.yaml.")
DEFAULT_GDRIVE_MOUNT = "/home/dung/cloud/gdrive"


def _gdrive_mount() -> Path:
    return Path(os.environ.get("VIDEOTOOL_GDRIVE_MOUNT", DEFAULT_GDRIVE_MOUNT)).resolve()


def _under_mount(folder: Path) -> bool:
    return Path(folder).resolve().is_relative_to(_gdrive_mount())


def prepare(folder: Path, target: str, creative_path: Path | None) -> int:
    """Prepare a job in place: storyboard, SRT, chapters, title cards, creative merge, parallax."""
    from videotool.creative.apply import apply_creative
    from videotool.creative.checks import pre_render_checks
    from videotool.creative.parallax import keep_title_cards_static
    from videotool.creative.prepare import prepare_job, run_cli, write_job

    if _under_mount(folder):
        typer.echo(f"refusing to prepare inside the gdrive mount ({_gdrive_mount()}): the mount is source "
                   "material. Stage it with `rclone copy` into ~/.cache/videotool/<name> first.", err=True)
        return 2
    creative: dict = {}
    if creative_path:
        creative = yaml.safe_load(creative_path.read_text(encoding="utf-8")) or {}
    try:
        data = prepare_job(folder, creative.get("inputs"), target)
        if creative:
            apply_creative(folder, data, creative)
            cap = (creative.get("render") or {}).get("bitrate_cap")
            if cap and target == "local":
                data.setdefault("render", {})["encoder"] = f"libx264-balanced-capped-{cap}"
        write_job(folder / "job.yaml", data)
        if (folder / "Parallax").is_dir():
            run_cli(["parallax-link", str(folder / "job.yaml"), "--clips-dir", str(folder / "Parallax")])
        if keep_title_cards_static(folder, folder / "job.yaml"):
            typer.echo("every story still is a Parallax/ clip -> enhance.parallax off (title cards stay static)")
        if target == "local":
            pre_render_checks(folder, folder / "job.yaml")
    except (CreativeError, RuntimeError, subprocess.CalledProcessError, FileNotFoundError) as exc:
        typer.echo(f"prepare failed: {exc}", err=True)
        return 1
    typer.echo(f"prepared {folder / 'job.yaml'} (target {target})")
    return 0


@creative_app.command("lint")
def lint_command(
    source: str = typer.Argument(..., help="Local episode folder or rclone remote (gdrive:…)."),
    creative: Path = typer.Option(..., "--creative", exists=True, dir_okay=False),
    series: Path | None = typer.Option(None, "--series", help="series.yaml (default: found from cwd)."),
    preview: Path | None = typer.Option(None, "--preview", help="Write the description preview here."),
    json_output: bool = typer.Option(False, "--json"),
    keep: bool = typer.Option(False, "--keep", help="Keep the stand-in job for inspection."),
) -> None:
    """Replay the render box's preparation on a stand-in of the episode and report problems."""
    from videotool.creative.lint import lint

    report = lint(source, creative, series, keep=keep)
    if preview and report.description is not None:
        preview.write_text(report.description, encoding="utf-8")
    if json_output:
        typer.echo(json.dumps({"errors": report.errors, "warnings": report.warnings, "summary": report.summary},
                              ensure_ascii=False, indent=2))
    else:
        for line in report.errors:
            typer.echo(f"ERROR   {line}")
        for line in report.warnings:
            typer.echo(f"WARNING {line}")
        for key, value in report.summary.items():
            typer.echo(f"{key:18} {value}")
        typer.echo(f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    raise typer.Exit(1 if report.errors else 0)


@creative_app.command("sfx-pin")
def sfx_pin_command(
    source: str = typer.Argument(..., help="Local episode folder or rclone remote holding the SRT."),
    picks: Path = typer.Option(..., "--picks", exists=True, dir_okay=False,
                               help="YAML list of {quote, near, file, gain_db?, note?}."),
    creative: Path = typer.Option(..., "--creative", dir_okay=False),
    pack: str | None = typer.Option(None, "--pack", help="SFX pack when creative.yaml names none."),
) -> None:
    """Pin each quoted beat to its exact time inside the SRT and write enhance.sfx.cues."""
    from videotool.creative.apply import SFX_LIBRARY
    from videotool.creative.rules import explain_sfx_cues, parse_srt, voice_end
    from videotool.creative.sfx_pin import pin_all, write_cues
    from videotool.creative.standin import list_files, read_head

    files = list_files(source)
    srts = [f for f in files if "/" not in f and f.endswith("_vi_qa.srt")] or \
        [f for f in files if "/" not in f and f.lower().endswith(".srt")]
    if not srts:
        typer.echo(f"no SRT at the root of {source}", err=True)
        raise typer.Exit(2)
    cues = parse_srt(read_head(source, srts[0], 64 * 1024 * 1024).decode("utf-8", errors="replace"))
    try:
        pinned = pin_all(yaml.safe_load(picks.read_text(encoding="utf-8")) or [], cues)
    except CreativeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    existing: dict = {}
    if creative.exists():
        existing = yaml.safe_load(creative.read_text(encoding="utf-8")) or {}
    pack = ((existing.get("enhance") or {}).get("sfx") or {}).get("pack") or pack
    kept_comments = write_cues(creative, pinned, pack)
    available = {p.name for p in (SFX_LIBRARY / pack).glob("*")} if pack else set()
    for cue, reason in explain_sfx_cues(pinned, available, voice_end(cues)):
        typer.echo(f"{cue['time']:>9.2f}  {'KEEP' if reason is None else 'DROP'}  {cue['file']}"
                   + (f"  ({reason})" if reason else ""))
    typer.echo(f"wrote {len(pinned)} cue(s) to {creative}"
               + ("" if kept_comments else " (file re-dumped: comments were not preserved)"))
