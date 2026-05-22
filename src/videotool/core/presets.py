from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputPreset:
    name: str
    width: int
    height: int
    fps: int
    video_bitrate: str
    subtitle_font_size: int

    @property
    def aspect(self) -> str:
        return f"{self.width}:{self.height}"


PRESETS: dict[str, OutputPreset] = {
    "youtube-16x9": OutputPreset("youtube-16x9", 1920, 1080, 30, "8M", 42),
    "shorts-9x16": OutputPreset("shorts-9x16", 1080, 1920, 30, "8M", 56),
}


def get_preset(name: str) -> OutputPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown output preset '{name}'. Expected one of: {choices}") from exc
