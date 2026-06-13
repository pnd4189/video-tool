from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path

from videotool.ai.align_script import align_script_to_transcript, parse_script
from videotool.core.chapter_timing import derive_chapters
from videotool.ai.faster_whisper_adapter import FasterWhisperTranscriber
from videotool.ai.silence import detect_silence, write_cut_suggestions
from videotool.ai.subtitles import write_srt
from videotool.assets.library import AssetLibrary, load_asset_index, validate_asset_paths
from videotool.assets.licenses import raise_on_blocking_issues, validate_asset_policy
from videotool.assets.reports import write_license_report
from videotool.core.job_spec import JobSpec, load_job, write_job_template
from videotool.core.errors import ValidationError
from videotool.core.media_probe import probe_media
from videotool.core.storyboard import natural_sort_key
from videotool.core.timeline import Timeline, compile_timeline
from videotool.core.validation import validate_job_paths
from videotool.package.manifest import write_package_manifest
from videotool.package.reports import write_quality_report
from videotool.package.thumbnails import generate_thumbnail_candidates
from videotool.package.youtube import (
    format_chapters_block,
    render_description_template,
    validate_package,
    write_description,
)
from videotool.render.commands import CommandPlan, build_ffmpeg_command
from videotool.render.cta_compose import compose_voice, offset_chapters, shift_srt
from videotool.render.executor import RenderExecutor, RenderResult
from videotool.render.music_loop import prepare_seamless_music
from videotool.render.profiles import RenderProfile, get_profile
from videotool.render.segmented import SegmentedPlan, build_segmented_render
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


@dataclass(frozen=True)
class _CtaRender:
    voice_path: Path
    intro_seconds: float
    outro_seconds: float
    intro_image: Path | None
    outro_image: Path | None


def _stage_voice_cta(job: JobSpec, job_path: Path, workspace_root: Path) -> _CtaRender | None:
    """Compose narration with optional intro/outro CTA clips into one track in the workspace.
    Returns None when no CTA is configured (the normal narration voice is used)."""
    if not job.inputs.intro_cta and not job.inputs.outro_cta:
        return None
    root = job_path.parent
    composed = compose_voice(
        root / job.inputs.voice,
        workspace_root / "voice-cta.flac",
        intro=(root / job.inputs.intro_cta) if job.inputs.intro_cta else None,
        outro=(root / job.inputs.outro_cta) if job.inputs.outro_cta else None,
    )
    return _CtaRender(
        voice_path=composed.path,
        intro_seconds=composed.intro_seconds,
        outro_seconds=composed.outro_seconds,
        intro_image=(root / job.inputs.intro_cta_image) if job.inputs.intro_cta_image else None,
        outro_image=(root / job.inputs.outro_cta_image) if job.inputs.outro_cta_image else None,
    )


def _compile_for_render(
    job_path: Path,
    presets: list[str] | None,
    subtitle_path: Path | None,
    music_path: Path | None,
    enhance_tier: str | None = None,
    cta: _CtaRender | None = None,
) -> tuple[Timeline, RenderProfile, list]:
    job = load_job(job_path)
    if enhance_tier is not None:
        job = job.model_copy(update={"enhance": job.enhance.model_copy(update={"tier": enhance_tier})})
    _raise_validation_errors(run_validate(job_path))
    selected = set(presets or [output.preset for output in job.outputs])
    available = {output.preset for output in job.outputs}
    unknown = selected - available
    if unknown:
        raise ValidationError(f"Requested preset is not in job outputs: {', '.join(sorted(unknown))}")
    voice_metadata = probe_media(cta.voice_path if cta else job_path.parent / job.inputs.voice)
    timeline = compile_timeline(
        job, job_path, duration=voice_metadata.duration,
        cta_voice_path=cta.voice_path if cta else None,
        cta_intro_seconds=cta.intro_seconds if cta else 0.0,
        cta_outro_seconds=cta.outro_seconds if cta else 0.0,
        cta_intro_image=cta.intro_image if cta else None,
        cta_outro_image=cta.outro_image if cta else None,
    )
    if subtitle_path is not None:
        timeline = replace(timeline, subtitle_path=subtitle_path)
    if music_path is not None:
        timeline = replace(timeline, music_path=music_path)
    profile = get_profile(job.render.encoder)
    outputs = [output for output in timeline.outputs if output.preset.name in selected]
    if not outputs:
        raise ValidationError("No render presets selected.")
    return timeline, profile, outputs


def build_render_plans(
    job_path: Path,
    presets: list[str] | None = None,
    subtitle_path: Path | None = None,
    music_path: Path | None = None,
    enhance_tier: str | None = None,
    cta: _CtaRender | None = None,
) -> list[CommandPlan]:
    timeline, profile, outputs = _compile_for_render(job_path, presets, subtitle_path, music_path, enhance_tier, cta)
    return [build_ffmpeg_command(timeline, profile, output) for output in outputs]


def build_segmented_plans(
    job_path: Path,
    presets: list[str] | None = None,
    subtitle_path: Path | None = None,
    music_path: Path | None = None,
    *,
    workspace_root: Path,
    enhance_tier: str | None = None,
    cta: _CtaRender | None = None,
) -> list[SegmentedPlan]:
    timeline, profile, outputs = _compile_for_render(job_path, presets, subtitle_path, music_path, enhance_tier, cta)
    # Per-preset clips/concat list: different resolutions can't share concat inputs.
    return [
        build_segmented_render(
            timeline,
            profile,
            output,
            clips_dir=workspace_root / "clips" / output.preset.name,
            concat_list_path=workspace_root / f"concat-{output.preset.name}.txt",
        )
        for output in outputs
    ]


def run_render(
    job_path: Path,
    presets: list[str] | None = None,
    dry_run: bool = False,
    enhance_tier: str | None = None,
) -> list[RenderResult] | list[CommandPlan] | list[SegmentedPlan]:
    job = load_job(job_path)
    if enhance_tier is not None:
        job = job.model_copy(update={"enhance": job.enhance.model_copy(update={"tier": enhance_tier})})
    _raise_validation_errors(run_validate(job_path))
    _require_burn_subtitles(job, job_path)
    library, _ = _load_library_for_job(job, job_path)
    issues = validate_asset_policy(library.records, job.assets.policy)
    raise_on_blocking_issues(issues)
    workspace = Workspace(job_path.parent / job.render.temp_dir)
    workspace.prepare()
    cta = _stage_voice_cta(job, job_path, workspace.root) if not dry_run else None
    subtitle_path = _stage_subtitle(job, job_path, workspace.root) if not dry_run else None
    music_path = _stage_music(job, job_path, workspace.root, cta) if not dry_run else None
    # Long storyboards render via the resumable clip-per-scene path; small ones keep
    # the single inline xfade filtergraph (preserves true crossfades + existing tests).
    if len(job.storyboard) > job.render.max_inline_scenes:
        segmented_plans = build_segmented_plans(
            job_path, presets, subtitle_path=subtitle_path, music_path=music_path,
            workspace_root=workspace.root, enhance_tier=enhance_tier, cta=cta,
        )
        if dry_run:
            return segmented_plans
        executor = RenderExecutor()
        return [executor.run_segmented(plan, workspace.logs_dir) for plan in segmented_plans]
    plans = build_render_plans(job_path, presets, subtitle_path=subtitle_path, music_path=music_path, enhance_tier=enhance_tier, cta=cta)
    if dry_run:
        return plans
    executor = RenderExecutor()
    return [
        executor.run(plan, workspace.logs_dir / f"{plan.preset}.log")
        for plan in plans
    ]


def run_transcribe(job_path: Path, model: str, script: Path | None = None) -> Path:
    job = load_job(job_path)
    _raise_validation_errors(run_validate(job_path))
    transcriber = FasterWhisperTranscriber(model_path=Path(model))
    transcript = transcriber.transcribe(job_path.parent / job.inputs.voice, language=job.project.language)
    # --script overrides inputs.script; both supply the polished wording.
    script_path = script or (job_path.parent / job.inputs.script if job.inputs.script else None)
    if script_path is not None:
        transcript = align_script_to_transcript(parse_script(script_path), transcript)
    output = job_path.parent / "outputs" / "captions.srt"
    write_srt(transcript, output)
    # An intro CTA plays before the narration in the final video, so captions + chapters must
    # shift by its duration. The artifacts stay aligned to the composed timeline produced at render.
    intro_seconds = 0.0
    if job.inputs.intro_cta:
        intro_seconds = probe_media(job_path.parent / job.inputs.intro_cta).duration or 0.0
    if intro_seconds > 0:
        output.write_text(shift_srt(output.read_text(encoding="utf-8"), intro_seconds), encoding="utf-8")
    # One whisper pass feeds both captions and YouTube chapters: derive chapter markers from
    # the same aligned transcript. Skip silently when fewer than 3 valid headings are found.
    chapters = derive_chapters(transcript)
    if chapters:
        chapters = offset_chapters(chapters, intro_seconds)
        chapters_path = job_path.parent / "outputs" / "chapters.json"
        chapters_path.write_text(
            json.dumps([{"start": start, "title": title} for start, title in chapters], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
    chapters = _load_chapters(job, output_dir)
    description_path = output_dir / "description.txt"
    if job.inputs.description_template is not None:
        template_text = (job_path.parent / job.inputs.description_template).read_text(encoding="utf-8")
        description_path.write_text(
            render_description_template(
                template_text,
                chapters_block=format_chapters_block(chapters),
                recap_prev=job.project.recap_previous,
                summary=job.project.description,
            ),
            encoding="utf-8",
        )
    else:
        write_description(
            job.project.title,
            output_dir / "license-report.md",
            description_path,
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


def _load_chapters(job: JobSpec, output_dir: Path) -> list[tuple[float, str]]:
    """Chapter markers for the description: prefer the whisper-derived outputs/chapters.json,
    fall back to job.project.chapters when it is absent."""
    chapters_path = output_dir / "chapters.json"
    if chapters_path.exists():
        data = json.loads(chapters_path.read_text(encoding="utf-8"))
        return [(float(entry["start"]), str(entry["title"])) for entry in data]
    return [(chapter.start, chapter.title) for chapter in job.project.chapters]


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
    if job.captions.mode != "srt-and-burn" and not job.enhance.is_on("subtitles"):
        return None
    source = job_path.parent / "outputs" / "captions.srt"
    if not source.exists():
        return None
    staged = workspace_root / "captions.srt"
    shutil.copyfile(source, staged)
    return staged


AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus")


def _resolve_music_tracks(music_path: Path) -> list[Path]:
    """Resolve ``inputs.music`` to an ordered track list. A directory expands to all audio
    files inside it, natural-sorted by filename (name tracks ``01-``, ``02-`` to order them);
    a single file resolves to a one-element list."""
    if music_path.is_dir():
        tracks = [
            path
            for path in music_path.iterdir()
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        ]
        return sorted(tracks, key=lambda path: natural_sort_key(path.name))
    return [music_path]


def _stage_music(job: JobSpec, job_path: Path, workspace_root: Path, cta: _CtaRender | None = None) -> Path | None:
    """Pre-render the music bed to span the full video (voice plus any ending extension)
    with crossfaded seams. Returns the prepared FLAC path so the main render uses it instead
    of the raw music file. Avoids the audible click at every loop boundary when a short music
    track is naively repeated under a long voice track. A music directory plays all its tracks
    in order, then loops."""
    if not job.inputs.music:
        return None
    voice_metadata = probe_media(job_path.parent / job.inputs.voice)
    if not voice_metadata.duration or voice_metadata.duration <= 0:
        return None
    # Cover the whole video: the storyboard can run past the voice (e.g. a 10s ending image).
    scenes_total = sum(scene.duration for scene in job.storyboard)
    # CTA clips extend the final video at both ends; the bed must cover them too.
    cta_seconds = (cta.intro_seconds + cta.outro_seconds) if cta else 0.0
    target_duration = max(voice_metadata.duration, scenes_total) + cta_seconds
    tracks = _resolve_music_tracks(job_path.parent / job.inputs.music)
    if not tracks:
        return None
    return prepare_seamless_music(
        music_paths=tracks,
        target_duration=target_duration,
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
    if (job.captions.mode == "srt-and-burn" or job.enhance.is_on("subtitles")) and not (job_path.parent / "outputs" / "captions.srt").exists():
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
    for scene in job.storyboard:
        if scene.image:
            used_paths.append((root / scene.image).resolve())
        if scene.video:
            used_paths.append((root / scene.video).resolve())
    if job.inputs.music:
        music_path = (root / job.inputs.music).resolve()
        if music_path.exists():
            used_paths.append(music_path)
    return [
        f"Used asset is missing license metadata: {path.relative_to(root)}"
        for path in used_paths
        if path not in indexed_paths
    ]
