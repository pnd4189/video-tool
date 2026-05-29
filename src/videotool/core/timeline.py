from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from videotool.core.job_spec import JobSpec
from videotool.core.presets import OutputPreset, get_preset


@dataclass(frozen=True)
class TimelineOutput:
    preset: OutputPreset
    output_path: Path


@dataclass(frozen=True)
class TimelineScene:
    scene: int
    media_path: Path
    duration: float
    motion: str
    transition: str
    caption: str = ""


@dataclass(frozen=True)
class Timeline:
    title: str
    root: Path
    voice_path: Path
    media_dir: Path
    music_path: Path | None
    caption_mode: str
    scenes: list[TimelineScene]
    outputs: list[TimelineOutput]
    duration: float | None = None
    description: str = ""
    author: str = ""
    subtitle_path: Path | None = None
    chapters: list[tuple[float, str]] = field(default_factory=list)
    voice_gain_db: float = 0.0
    music_gain_db: float = -28.0
    duck: bool = True
    normalize_lufs: float | None = -14.0
    # Silence appended to the voice so it spans the full video when scenes (e.g. an ending
    # image) extend past the narration. Keeps `-shortest` from truncating the outro.
    voice_pad_seconds: float = 0.0


def compile_timeline(job: JobSpec, job_path: Path, duration: float | None = None) -> Timeline:
    root = job_path.parent
    outputs = [
        TimelineOutput(
            preset=get_preset(output.preset),
            output_path=root / "outputs" / f"{output.preset}.mp4",
        )
        for output in job.outputs
    ]
    scenes = [
        TimelineScene(
            scene=scene.scene,
            media_path=(root / scene.image).resolve(),
            duration=scene.duration,
            motion=scene.motion,
            transition=scene.transition,
            caption=scene.caption,
        )
        for scene in job.storyboard
    ]
    chapters = [(chapter.start, chapter.title) for chapter in job.project.chapters]
    scenes_total = sum(scene.duration for scene in scenes)
    voice_pad_seconds = max(0.0, scenes_total - duration) if duration else 0.0
    return Timeline(
        title=job.project.title,
        root=root,
        voice_path=(root / job.inputs.voice).resolve(),
        media_dir=(root / job.inputs.media_dir).resolve(),
        music_path=(root / job.inputs.music).resolve() if job.inputs.music else None,
        caption_mode=job.captions.mode,
        scenes=scenes,
        outputs=outputs,
        duration=duration,
        description=job.project.description,
        author=job.project.author,
        chapters=chapters,
        voice_gain_db=job.audio.voice_gain_db,
        music_gain_db=job.audio.music_gain_db,
        duck=job.audio.duck,
        normalize_lufs=job.audio.normalize_lufs,
        voice_pad_seconds=voice_pad_seconds,
    )
