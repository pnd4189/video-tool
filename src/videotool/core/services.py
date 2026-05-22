from __future__ import annotations

import json
import shutil
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path

from videotool.ai.faster_whisper_adapter import FasterWhisperTranscriber
from videotool.ai.silence import detect_silence, write_cut_suggestions
from videotool.ai.subtitles import write_srt
from videotool.assets.library import AssetLibrary, load_asset_index, validate_asset_paths
from videotool.assets.licenses import raise_on_blocking_issues, validate_asset_policy
from videotool.assets.reports import write_license_report
from videotool.core.job_spec import JobSpec, load_job, write_job_template
from videotool.core.errors import ValidationError
from videotool.core.media_probe import probe_media
from videotool.core.timeline import Timeline, compile_timeline
from videotool.core.validation import validate_job_paths
from videotool.package.manifest import write_package_manifest
from videotool.package.reports import write_quality_report
from videotool.package.thumbnails import generate_thumbnail_candidates
from videotool.package.youtube import validate_package, write_description
from videotool.render.commands import CommandPlan, build_ffmpeg_command
from videotool.render.executor import RenderExecutor, RenderResult
from videotool.render.music_loop import prepare_seamless_music
from videotool.render.profiles import get_profile
from videotool.render.workspace import Workspace


def run_init_job(job_dir: Path, voice: str, media: str, music: str | None = None) -> Path:
    job_path = job_dir / "job.yaml"
    write_job_template(job_path, title=job_dir.name, voice=voice, media_dir=media, music=music)
    return job_path


def run_validate(job_path: Path, require_existing: bool = True) -> list[str]:
    job = load_job(job_path)
    errors = validate_job_paths(job, job_path, require_existing=require_existing)
    library, index_errors = _load_library_for_job(job, job_path)
    errors.extend(index_errors)
    errors.extend(validate_asset_paths(library, job_path.parent / "assets"))
    errors.extend(_validate_used_assets(job, job_path, library))
    issues = validate_asset_policy(library.records, job.assets.policy)
    errors.extend(f"{issue.asset_id}: {issue.message}" for issue in issues if issue.severity == "fail")
    return errors


def run_probe(job_path: Path) -> dict[str, object]:
    job = load_job(job_path)
    _raise_validation_errors(run_validate(job_path))
    root = job_path.parent
    voice = probe_media(root / job.inputs.voice)
    payload: dict[str, object] = {"voice": voice.__dict__}
    if job.inputs.music:
        payload["music"] = probe_media(root / job.inputs.music).__dict__
    return payload


def build_render_plans(
    job_path: Path,
    presets: list[str] | None = None,
    subtitle_path: Path | None = None,
    music_path: Path | None = None,
) -> list[CommandPlan]:
    job = load_job(job_path)
    _raise_validation_errors(run_validate(job_path))
    selected = set(presets or [output.preset for output in job.outputs])
    available = {output.preset for output in job.outputs}
    unknown = selected - available
    if unknown:
        raise ValidationError(f"Requested preset is not in job outputs: {', '.join(sorted(unknown))}")
    voice_metadata = probe_media(job_path.parent / job.inputs.voice)
    timeline = compile_timeline(job, job_path, duration=voice_metadata.duration)
    if subtitle_path is not None:
        timeline = replace(timeline, subtitle_path=subtitle_path)
    if music_path is not None:
        timeline = replace(timeline, music_path=music_path)
    profile = get_profile(job.render.encoder)
    plans = [
        build_ffmpeg_command(timeline, profile, output)
        for output in timeline.outputs
        if output.preset.name in selected
    ]
    if not plans:
        raise ValidationError("No render presets selected.")
    return plans


def run_render(job_path: Path, presets: list[str] | None = None, dry_run: bool = False) -> list[RenderResult] | list[CommandPlan]:
    job = load_job(job_path)
    _raise_validation_errors(run_validate(job_path))
    _require_burn_subtitles(job, job_path)
    library, _ = _load_library_for_job(job, job_path)
    issues = validate_asset_policy(library.records, job.assets.policy)
    raise_on_blocking_issues(issues)
    workspace = Workspace(job_path.parent / job.render.temp_dir)
    workspace.prepare()
    subtitle_path = _stage_subtitle(job, job_path, workspace.root) if not dry_run else None
    music_path = _stage_music(job, job_path, workspace.root) if not dry_run else None
    plans = build_render_plans(job_path, presets, subtitle_path=subtitle_path, music_path=music_path)
    if dry_run:
        return plans
    executor = RenderExecutor()
    return [
        executor.run(plan, workspace.logs_dir / f"{plan.preset}.log")
        for plan in plans
    ]


def run_transcribe(job_path: Path, model: str) -> Path:
    job = load_job(job_path)
    _raise_validation_errors(run_validate(job_path))
    transcriber = FasterWhisperTranscriber(model_path=Path(model))
    transcript = transcriber.transcribe(job_path.parent / job.inputs.voice, language=job.project.language)
    output = job_path.parent / "outputs" / "captions.srt"
    write_srt(transcript, output)
    return output


def run_analyze_audio(job_path: Path) -> Path:
    job = load_job(job_path)
    _raise_validation_errors(run_validate(job_path))
    ranges = detect_silence(job_path.parent / job.inputs.voice)
    output = job_path.parent / "outputs" / "cut-suggestions.md"
    write_cut_suggestions(ranges, output)
    return output


def run_package(job_path: Path) -> list[object]:
    job: JobSpec = load_job(job_path)
    _raise_validation_errors(run_validate(job_path))
    output_dir = job_path.parent / "outputs"
    library, _ = _load_library_for_job(job, job_path)
    issues = validate_asset_policy(library.records, job.assets.policy)
    write_license_report(library, output_dir / "license-report.md", issues)
    chapters = [(chapter.start, chapter.title) for chapter in job.project.chapters]
    write_description(
        job.project.title,
        output_dir / "license-report.md",
        output_dir / "description.txt",
        description=job.project.description,
        chapters=chapters,
        tags=job.project.tags,
        cta=job.project.cta,
    )
    _generate_thumbnails(output_dir, [f"{output.preset}.mp4" for output in job.outputs])
    expected_videos = [f"{output.preset}.mp4" for output in job.outputs]
    checks = validate_package(output_dir, expected_videos=expected_videos, require_srt=job.package.write_srt)
    write_quality_report(checks, output_dir / "quality-report.json")
    manifest_path = output_dir / "package-manifest.json"
    files = sorted(path for path in output_dir.iterdir() if path.is_file() and path != manifest_path)
    write_package_manifest(files, job_path, manifest_path)
    return checks


def json_default(value: object) -> str:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def to_json(value: object) -> str:
    return json.dumps(value, default=json_default, indent=2)


def _stage_subtitle(job: JobSpec, job_path: Path, workspace_root: Path) -> Path | None:
    """Copy outputs/captions.srt to a short ASCII-safe path inside the workspace before
    render. ffmpeg's subtitles filter is fragile with paths containing spaces, single
    quotes, or filtergraph metacharacters; staging avoids those entirely."""
    if job.captions.mode != "srt-and-burn":
        return None
    source = job_path.parent / "outputs" / "captions.srt"
    if not source.exists():
        return None
    staged = workspace_root / "captions.srt"
    shutil.copyfile(source, staged)
    return staged


def _stage_music(job: JobSpec, job_path: Path, workspace_root: Path) -> Path | None:
    """Pre-render the music track to exactly match the voice duration with crossfaded
    seams. Returns the prepared FLAC path so the main render uses it instead of the
    raw music file. Avoids the audible click at every loop boundary when a short
    music track is naively repeated under a long voice track."""
    if not job.inputs.music:
        return None
    voice_metadata = probe_media(job_path.parent / job.inputs.voice)
    if not voice_metadata.duration or voice_metadata.duration <= 0:
        return None
    return prepare_seamless_music(
        music_path=job_path.parent / job.inputs.music,
        target_duration=voice_metadata.duration,
        workspace_root=workspace_root,
    )


def _generate_thumbnails(output_dir: Path, expected_videos: list[str]) -> None:
    """Generate thumbnail candidates from the first available rendered video.
    Prefer the 16:9 long-form output for the YouTube primary thumbnail; otherwise
    fall back to whatever is on disk so Shorts-only workflows still produce one."""
    primary_candidates = [
        output_dir / "youtube-16x9.mp4",
        *(output_dir / name for name in expected_videos),
    ]
    for candidate in primary_candidates:
        if candidate.exists():
            try:
                generate_thumbnail_candidates(candidate, output_dir, count=5)
            except Exception:
                # Thumbnail failure must not poison the package step.
                pass
            return


def _load_library_for_job(job: JobSpec, job_path: Path) -> tuple[AssetLibrary, list[str]]:
    index_path = job_path.parent / "assets" / "asset-index.yaml"
    if not index_path.exists() and job.assets.policy == "licensed-only":
        return AssetLibrary(), [f"Asset index is required by licensed-only policy: {index_path}"]
    return load_asset_index(index_path), []


def _raise_validation_errors(errors: list[str]) -> None:
    if errors:
        raise ValidationError("; ".join(errors))


def _require_burn_subtitles(job: JobSpec, job_path: Path) -> None:
    if job.captions.mode == "srt-and-burn" and not (job_path.parent / "outputs" / "captions.srt").exists():
        raise ValidationError("captions.mode is srt-and-burn but outputs/captions.srt is missing.")


def _validate_used_assets(job: JobSpec, job_path: Path, library: AssetLibrary) -> list[str]:
    if job.assets.policy != "licensed-only":
        return []
    root = job_path.parent.resolve()
    asset_root = root / "assets"
    indexed_paths = {(asset_root / record.path).resolve() for record in library.records}
    used_paths: list[Path] = []
    media_dir = (root / job.inputs.media_dir).resolve()
    if media_dir.exists():
        # Recursive walk: subfolders must not bypass the licensed-only policy.
        used_paths.extend(path.resolve() for path in media_dir.rglob("*") if path.is_file())
    used_paths.extend((root / scene.image).resolve() for scene in job.storyboard)
    if job.inputs.music:
        music_path = (root / job.inputs.music).resolve()
        if music_path.exists():
            used_paths.append(music_path)
    return [
        f"Used asset is missing license metadata: {path.relative_to(root)}"
        for path in used_paths
        if path not in indexed_paths
    ]
