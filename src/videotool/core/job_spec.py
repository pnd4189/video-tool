from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from videotool.core.presets import PRESETS


class ChapterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0)
    title: str = Field(min_length=1)


class ProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    language: str = "vi"
    description: str = ""
    # Recap of the previous episode, shown above this episode's summary so viewers can catch up.
    recap_previous: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    chapters: list[ChapterSpec] = Field(default_factory=list)
    cta: str = ""


class InputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice: Path
    media_dir: Path = Path("media")
    music: Path | None = None
    # Polished prose script; when set, subtitles use its wording with whisper timing.
    script: Path | None = None
    # Optional thumbnail-template shown over the first seconds of the voice (no added time).
    intro_image: Path | None = None
    # Optional ending image appended as an extra outro after the voice ends.
    ending_image: Path | None = None
    # Optional particle/grain overlay used by enhance.tier=full; bundled default is used when unset.
    particle_overlay: Path | None = None
    # Optional description template (with {{CHAPTERS}}/{{RECAP_PREV}}/{{SUMMARY}} placeholders);
    # when set, package renders outputs/description.txt from it instead of the generic format.
    description_template: Path | None = None
    # Optional CTA voice clips spliced at the very start / very end of the narration. Their
    # title-card images (intro_cta_image / outro_cta_image) show while they play; when an image
    # is unset the first / last storyboard image is held instead.
    intro_cta: Path | None = None
    outro_cta: Path | None = None
    intro_cta_image: Path | None = None
    outro_cta_image: Path | None = None


class OutputSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: str

    @field_validator("preset")
    @classmethod
    def known_preset(cls, value: str) -> str:
        if value not in PRESETS:
            choices = ", ".join(sorted(PRESETS))
            raise ValueError(f"Unknown preset '{value}'. Expected one of: {choices}")
        return value


class StoryboardSceneSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene: int = Field(gt=0)
    # A scene renders from either a still image (with zoompan motion) or a video clip.
    # At least one must be set; when both are present the video clip wins (see timeline).
    image: Path | None = None
    video: Path | None = None
    duration: float = Field(gt=0)
    motion: Literal[
        "zoom-in",
        "zoom-out",
        "slow-push",
        "pan-left",
        "pan-right",
        "pan-up",
        "pan-down",
        "ken-burns",
        "static",
    ] = "slow-push"
    transition: Literal["cut", "fade", "crossfade", "dip-to-black"] = "crossfade"
    caption: str = ""

    @model_validator(mode="after")
    def require_media(self) -> "StoryboardSceneSpec":
        if self.image is None and self.video is None:
            raise ValueError("Each storyboard scene needs an 'image' or a 'video'.")
        return self


class AudioSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_gain_db: float = 0.0
    # Low enough that a gentle music bed never competes with narration on audio-story videos.
    music_gain_db: float = -30.0
    duck: bool = True
    # When None, the final loudnorm pass is dropped and dB gains become absolute.
    normalize_lufs: float | None = -14.0


class CaptionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "srt-only", "srt-and-burn"] = "srt-only"


# Overlay features the "full" tier turns on. Each has a per-feature override on EnhanceSpec.
ENHANCE_FEATURES = ("subtitles", "particles", "progress_bar", "visualizer")


class EnhanceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Master switch. light = current fast path (zoompan + concat-BGM, segmented `-c:v copy`).
    # full = overlay package re-encoded once (subtitles/particles/progress bar/visualizer).
    tier: Literal["light", "full"] = "light"
    # Per-feature overrides: None follows the tier; a bool forces the feature on/off.
    subtitles: bool | None = None
    particles: bool | None = None
    progress_bar: bool | None = None
    visualizer: bool | None = None
    # Depth-based 2.5D parallax on still scenes. Independent of tier (expensive + offline):
    # it is OFF unless explicitly set true, so tier=full never silently enables it.
    parallax: bool = False

    def is_on(self, feature: str) -> bool:
        """Resolve a single overlay feature: explicit override wins, else follow the tier."""
        if feature not in ENHANCE_FEATURES:
            raise ValueError(f"Unknown enhance feature '{feature}'. Expected one of: {', '.join(ENHANCE_FEATURES)}")
        override = getattr(self, feature)
        if override is not None:
            return override
        return self.tier == "full"


class AssetPolicySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: Literal["licensed-only", "allow-missing-local", "strict-attribution"] = "licensed-only"


class RenderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encoder: str = "libx264-balanced"
    temp_dir: Path = Path(".videotool/tmp")
    seed: int = 1
    # Above this scene count, render via the resumable segmented path (clip-per-scene
    # + concat) instead of one giant filtergraph. Tune per job for RAM/length trade-offs.
    max_inline_scenes: int = Field(default=40, gt=0)


class PackageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    write_srt: bool = True
    write_thumbnail: bool = True
    write_description: bool = True
    write_license_report: bool = True
    write_quality_report: bool = True


class JobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    project: ProjectSpec
    inputs: InputSpec
    outputs: list[OutputSpec] = Field(default_factory=lambda: [OutputSpec(preset="youtube-16x9")])
    storyboard: list[StoryboardSceneSpec] = Field(default_factory=list)
    audio: AudioSpec = Field(default_factory=AudioSpec)
    captions: CaptionSpec = Field(default_factory=CaptionSpec)
    enhance: EnhanceSpec = Field(default_factory=EnhanceSpec)
    assets: AssetPolicySpec = Field(default_factory=AssetPolicySpec)
    render: RenderSpec = Field(default_factory=RenderSpec)
    package: PackageSpec = Field(default_factory=PackageSpec)

    @field_validator("version")
    @classmethod
    def supported_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Unsupported job schema version. This release supports version 1.")
        return value

    @model_validator(mode="after")
    def require_outputs(self) -> "JobSpec":
        if not self.outputs:
            raise ValueError("At least one output preset is required.")
        return self


def load_job(path: Path) -> JobSpec:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Job file must contain a YAML mapping: {path}")
    return JobSpec.model_validate(data)


def write_job_template(path: Path, title: str, voice: str, media_dir: str, music: str | None) -> None:
    data = {
        "version": 1,
        "project": {"title": title, "language": "vi"},
        "inputs": {"voice": voice, "media_dir": media_dir},
        "outputs": [{"preset": "youtube-16x9"}],
        "captions": {"mode": "srt-only"},
        "assets": {"policy": "licensed-only"},
        "render": {"encoder": "libx264-balanced", "temp_dir": ".videotool/tmp"},
    }
    if music:
        data["inputs"]["music"] = music
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
