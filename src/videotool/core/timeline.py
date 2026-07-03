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
    particle_overlay_path: Path | None = None
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
    # Resolved overlay tier. light (default) = current fast render, byte-identical output.
    # full = overlay package; per-feature flags below are resolved from EnhanceSpec.
    enhance_tier: str = "light"
    enhance_subtitles: bool = False
    enhance_particles: bool = False
    enhance_visualizer: bool = False
    # Group A filter effects (mood-resolved) + atmospheric overlay blend.
    enhance_vignette: bool = False
    enhance_grain: bool = False
    enhance_glow: bool = False
    enhance_flicker: bool = False
    enhance_atmosphere: bool = False
    enhance_color_grade: str | None = None
    # Burned-subtitle fill colour ("white" default, "yellow" for audio-story legibility).
    enhance_subtitle_color: str = "white"


def compile_timeline(
    job: JobSpec,
    job_path: Path,
    duration: float | None = None,
    *,
    cta_voice_path: Path | None = None,
    cta_intro_seconds: float = 0.0,
    cta_outro_seconds: float = 0.0,
    cta_intro_image: Path | None = None,
    cta_outro_image: Path | None = None,
) -> Timeline:
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
            media_path=(root / (scene.video if scene.video else scene.image)).resolve(),
            duration=scene.duration,
            motion=scene.motion,
            transition=scene.transition,
            caption=scene.caption,
        )
        for scene in job.storyboard
    ]
    # CTA title cards bracket the narration scenes: the intro card shows while the intro CTA
    # plays, the outro card while the outro CTA plays. Image defaults to the first / last scene.
    if scenes and cta_intro_seconds > 0:
        intro_img = cta_intro_image.resolve() if cta_intro_image else scenes[0].media_path
        scenes.insert(0, TimelineScene(scene=0, media_path=intro_img, duration=cta_intro_seconds, motion="slow-push", transition="cut"))
    if scenes and cta_outro_seconds > 0:
        outro_img = cta_outro_image.resolve() if cta_outro_image else scenes[-1].media_path
        scenes.append(TimelineScene(scene=scenes[-1].scene + 1, media_path=outro_img, duration=cta_outro_seconds, motion="slow-push", transition="cut"))
    chapters = [(chapter.start, chapter.title) for chapter in job.project.chapters]
    scenes_total = sum(scene.duration for scene in scenes)
    voice_pad_seconds = max(0.0, scenes_total - duration) if duration else 0.0
    return Timeline(
        title=job.project.title,
        root=root,
        voice_path=cta_voice_path.resolve() if cta_voice_path else (root / job.inputs.voice).resolve(),
        media_dir=(root / job.inputs.media_dir).resolve(),
        music_path=(root / job.inputs.music).resolve() if job.inputs.music else None,
        particle_overlay_path=(root / job.inputs.particle_overlay).resolve() if job.inputs.particle_overlay else None,
        caption_mode="srt-and-burn" if job.enhance.is_on("subtitles") else job.captions.mode,
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
        enhance_tier=job.enhance.tier,
        enhance_subtitles=job.enhance.is_on("subtitles"),
        enhance_particles=job.enhance.is_on("particles"),
        enhance_visualizer=job.enhance.is_on("visualizer"),
        enhance_vignette=job.enhance.effect_on("vignette"),
        enhance_grain=job.enhance.effect_on("grain"),
        enhance_glow=job.enhance.effect_on("glow"),
        enhance_flicker=job.enhance.effect_on("flicker"),
        enhance_atmosphere=job.enhance.atmosphere,
        enhance_color_grade=job.enhance.resolved_color_grade(),
        enhance_subtitle_color=job.enhance.subtitle_color,
    )
