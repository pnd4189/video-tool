from __future__ import annotations

from pathlib import Path
from typing import Literal

import typer

from videotool import __version__
from videotool.cli import commands
from videotool.cli.storyboard_commands import auto_storyboard, plan_storyboard

app = typer.Typer(no_args_is_help=True)
storyboard_app = typer.Typer(no_args_is_help=True)
app.add_typer(storyboard_app, name="storyboard")


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def doctor(json_output: bool = typer.Option(False, "--json")) -> None:
    commands.doctor(json_output=json_output)


@app.command("init-job")
def init_job(
    job_dir: Path,
    voice: str = typer.Option(..., "--voice"),
    media: str = typer.Option("media", "--media"),
    music: str | None = typer.Option(None, "--music"),
) -> None:
    commands.init_job(job_dir, voice, media, music)


@app.command()
def parallax(
    image: Path,
    out: Path,
    duration: float = typer.Option(6.0, "--duration"),
    fps: int = typer.Option(30, "--fps"),
    width: int = typer.Option(1920, "--width"),
    height: int = typer.Option(1080, "--height"),
) -> None:
    raise typer.Exit(commands.parallax(image, out, duration, fps, width, height))


@app.command()
def validate(job_path: Path, json_output: bool = typer.Option(False, "--json")) -> None:
    raise typer.Exit(commands.validate(job_path, json_output=json_output))


@app.command("parallax-link")
def parallax_link(
    job_path: Path,
    clips_dir: Path = typer.Option(Path("Parallax"), "--clips-dir"),
) -> None:
    raise typer.Exit(commands.parallax_link(job_path, clips_dir))


@app.command()
def probe(job_path: Path, json_output: bool = typer.Option(False, "--json")) -> None:
    raise typer.Exit(commands.probe(job_path, json_output=json_output))


@app.command()
def render(
    job_path: Path,
    preset: list[str] = typer.Option(None, "--preset"),
    all_presets: bool = typer.Option(False, "--all"),
    dry_run: bool = False,
    json_output: bool = typer.Option(False, "--json"),
    enhance: Literal["light", "full"] | None = typer.Option(None, "--enhance"),
) -> None:
    raise typer.Exit(commands.render(job_path, preset, all_presets, dry_run, json_output, enhance))


@app.command()
def batch(root: Path, jobs: int = 1, dry_run: bool = False) -> None:
    raise typer.Exit(commands.batch(root, jobs, dry_run))


@app.command()
def transcribe(
    job_path: Path,
    model: str = typer.Option(..., "--model", help="Local faster-whisper model path or HuggingFace model id (e.g. large-v3)."),
    script: Path = typer.Option(None, "--script", help="Polished prose script; its wording is used with whisper timing."),
    device: str = typer.Option("cpu", "--device", help="Compute device: cpu (default) or cuda."),
    compute_type: str = typer.Option("int8", "--compute-type", help="Quantization: int8 (default, CPU) or float16 (GPU)."),
) -> None:
    raise typer.Exit(commands.transcribe(job_path, model, script, device, compute_type))


@app.command("analyze-audio")
def analyze_audio(job_path: Path) -> None:
    raise typer.Exit(commands.analyze_audio(job_path))


@app.command("package")
def package_cmd(job_path: Path) -> None:
    raise typer.Exit(commands.package(job_path))


@app.command()
def benchmark(job_path: Path, profiles: str = "libx264-balanced,h264-vaapi-draft") -> None:
    commands.benchmark(job_path, profiles)


@app.command()
def gui(host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter("Install GUI extras first: pip install -e '.[gui]'") from exc
    from videotool.gui.app import create_app

    uvicorn.run(create_app(), host=host, port=port)


@storyboard_app.command("plan")
def storyboard_plan(
    image_prompts: Path = typer.Option(..., "--image-prompts"),
    video_prompts: Path = typer.Option(..., "--video-prompts"),
    media: Path = typer.Option(..., "--media"),
    voice: str = typer.Option(..., "--voice"),
    output: Path = typer.Option(..., "--output"),
    music: str | None = typer.Option(None, "--music"),
    title: str | None = typer.Option(None, "--title"),
) -> None:
    plan_storyboard(image_prompts, video_prompts, media, voice, output, music, title)


@storyboard_app.command("auto")
def storyboard_auto(
    job_path: Path,
    images_dir: Path = typer.Option(..., "--images-dir"),
    videos_dir: Path | None = typer.Option(None, "--videos-dir"),
) -> None:
    auto_storyboard(job_path, images_dir, videos_dir=videos_dir)
