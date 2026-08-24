from __future__ import annotations

from pathlib import Path

from rich.table import Table

from videotool.core.errors import DependencyError, LicensePolicyError, RenderError, VideoToolError
from videotool.core.logging import console
from videotool.package.metadata import run_metadata
from videotool.core.services import (
    build_render_plans,
    run_analyze_audio,
    run_init_job,
    run_package,
    run_probe,
    run_chapters_from_srt,
    run_render,
    run_sfx,
    run_transcribe,
    run_validate,
    to_json,
)

CONFIG_ERROR = 2
DEPENDENCY_ERROR = 3
RENDER_ERROR = 4
LICENSE_BLOCK = 5
VALIDATION_FAILURE = 6


def doctor(json_output: bool = False) -> None:
    import shutil
    import sys

    from videotool.render.parallax import parallax_available

    payload = {
        "python": sys.version.split()[0],
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "parallax_extra": parallax_available(),
    }
    if json_output:
        print(to_json(payload))
        return
    table = Table("Check", "Status")
    for key, value in payload.items():
        table.add_row(key, str(value))
    console.print(table)


def init_job(job_dir: Path, voice: str, media: str, music: str | None) -> None:
    console.print(f"Created {run_init_job(job_dir, voice, media, music)}")


def parallax(image: Path, out: Path, duration: float, fps: int, width: int, height: int) -> int:
    """Render one depth-parallax clip from a single still (for testing the effect)."""
    from videotool.render.parallax import PARALLAX_MISSING_MSG, parallax_available, render_parallax_clip

    if not parallax_available():
        console.print(f"[red]MISSING DEPENDENCY[/red] {PARALLAX_MISSING_MSG}")
        return DEPENDENCY_ERROR
    render_parallax_clip(image, duration, fps, width, height, out)
    console.print(out)
    return 0


def parallax_link(job_path: Path, clips_dir: Path) -> int:
    from videotool.cli.storyboard_commands import link_parallax

    try:
        link_parallax(job_path, clips_dir)
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    return 0


def validate(job_path: Path, json_output: bool = False) -> int:
    try:
        errors = run_validate(job_path)
    except (ValueError, VideoToolError) as exc:
        errors = [str(exc)]
    if json_output:
        print(to_json({"valid": not errors, "errors": errors}))
    elif errors:
        for error in errors:
            console.print(f"[red]ERROR[/red] {error}")
    else:
        console.print("[green]OK[/green] job is valid")
    return 0 if not errors else VALIDATION_FAILURE


def probe(job_path: Path, json_output: bool = False) -> int:
    try:
        payload = run_probe(job_path)
    except DependencyError as exc:
        console.print(f"[red]MISSING DEPENDENCY[/red] {exc}")
        return DEPENDENCY_ERROR
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    if json_output:
        print(to_json(payload))
    else:
        console.print(payload)
    return 0


def render(
    job_path: Path,
    presets: list[str] | None,
    all_presets: bool,
    dry_run: bool,
    json_output: bool,
    enhance_tier: str | None = None,
) -> int:
    selected = None if all_presets else presets
    try:
        result = run_render(job_path, selected, dry_run=dry_run, enhance_tier=enhance_tier)
    except LicensePolicyError as exc:
        console.print(f"[red]LICENSE BLOCK[/red] {exc}")
        return LICENSE_BLOCK
    except DependencyError as exc:
        console.print(f"[red]MISSING DEPENDENCY[/red] {exc}")
        return DEPENDENCY_ERROR
    except RenderError as exc:
        console.print(f"[red]RENDER FAILED[/red] {exc}")
        return RENDER_ERROR
    except VideoToolError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    if json_output:
        print(to_json(result))
    else:
        for item in result:
            if not dry_run:
                console.print(item.output_path)
            elif hasattr(item, "scene_commands"):
                console.print(f"{item.preset}: {len(item.scene_commands)} scene clip(s) + 1 mux")
                for scene in item.scene_commands:
                    console.print(scene.command)
                console.print(item.mux_command)
            else:
                console.print(item.command)
    return 0


def batch(root: Path, jobs: int, dry_run: bool) -> int:
    job_paths = sorted(root.glob("*/job.yaml"))
    if not job_paths:
        return 0
    jobs = max(1, jobs)
    if jobs == 1 or dry_run or len(job_paths) == 1:
        for job_path in job_paths:
            console.print(f"Running {job_path}")
            code = render(job_path, None, True, dry_run, False)
            if code != 0:
                return code
        return 0

    from concurrent.futures import ProcessPoolExecutor, as_completed
    console.print(f"[cyan]Running {len(job_paths)} jobs across {jobs} workers[/cyan]")
    failures: list[int] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_render_in_worker, job_path, dry_run): job_path for job_path in job_paths}
        for future in as_completed(futures):
            job_path = futures[future]
            code = future.result()
            status = "ok" if code == 0 else f"exit {code}"
            console.print(f"Finished {job_path}: {status}")
            if code != 0:
                failures.append(code)
    return failures[0] if failures else 0


def _render_in_worker(job_path: Path, dry_run: bool) -> int:
    # Top-level helper so it is picklable across ProcessPoolExecutor workers.
    return render(job_path, None, True, dry_run, False)


def transcribe(
    job_path: Path,
    model: str,
    script: Path | None = None,
    device: str = "cpu",
    compute_type: str = "int8",
) -> int:
    try:
        console.print(
            f"Wrote {run_transcribe(job_path, model=model, script=script, device=device, compute_type=compute_type)}"
        )
    except DependencyError as exc:
        console.print(f"[red]MISSING DEPENDENCY[/red] {exc}")
        return DEPENDENCY_ERROR
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    return 0


def chapters_from_srt(job_path: Path) -> int:
    try:
        result = run_chapters_from_srt(job_path)
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    if result is None:
        console.print("No chapters written (fewer than 3 'Chương N:' markers found in SRT).")
    else:
        console.print(f"Wrote {result}")
    return 0


def sfx(job_path: Path) -> int:
    try:
        processed = run_sfx(job_path)
    except DependencyError as exc:
        console.print(f"[red]MISSING DEPENDENCY[/red] {exc}")
        return DEPENDENCY_ERROR
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    if not processed:
        console.print("No SFX mixed (enhance.sfx unset/disabled or no cues).")
    else:
        console.print(f"Mixed SFX onto {len(processed)} output(s): {', '.join(p.name for p in processed)}")
    return 0


def metadata(job_path: Path, rename: bool = True) -> int:
    try:
        tagged, published = run_metadata(job_path, rename=rename)
    except DependencyError as exc:
        console.print(f"[red]MISSING DEPENDENCY[/red] {exc}")
        return DEPENDENCY_ERROR
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    console.print(f"Tagged {len(tagged)} output(s).")
    if published is not None:
        console.print(f"Published name: {published.name}")
    return 0


def analyze_audio(job_path: Path) -> int:
    try:
        console.print(f"Wrote {run_analyze_audio(job_path)}")
    except DependencyError as exc:
        console.print(f"[red]MISSING DEPENDENCY[/red] {exc}")
        return DEPENDENCY_ERROR
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    return 0


def package(job_path: Path) -> int:
    try:
        checks = run_package(job_path)
    except DependencyError as exc:
        console.print(f"[red]MISSING DEPENDENCY[/red] {exc}")
        return DEPENDENCY_ERROR
    except (ValueError, VideoToolError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        return CONFIG_ERROR
    for check in checks:
        console.print(f"{check.status.upper()} {check.name}: {check.message}")
    return 0 if all(check.status != "fail" for check in checks) else VALIDATION_FAILURE


def benchmark(job_path: Path, profiles: str) -> None:
    for profile in profiles.split(","):
        plans = build_render_plans(job_path)
        console.print(f"{profile}: {len(plans)} command(s) available for benchmark dry-run")
