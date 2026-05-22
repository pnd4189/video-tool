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
    )
