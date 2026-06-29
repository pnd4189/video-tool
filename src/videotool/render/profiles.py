from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderProfile:
    name: str
    encoder: str
    preset: str | None
    crf: int | None
    extra_args: tuple[str, ...] = ()


# Only libx264 profiles are wired end-to-end in V1. VAAPI/AV1/HEVC profiles need
# -vaapi_device + hwupload filter chains that the command builder does not emit yet;
# they were removed to prevent producing broken ffmpeg commands at runtime.
PROFILES = {
    "libx264-balanced": RenderProfile("libx264-balanced", "libx264", "medium", 20),
    "libx264-fast": RenderProfile("libx264-fast", "libx264", "veryfast", 23),
    # Same quality as balanced (medium/CRF20) with a VBV ceiling so a long video stays
    # under a size budget. Peaks cap at maxrate; the long-run average never exceeds it.
    "libx264-balanced-capped": RenderProfile(
        "libx264-balanced-capped", "libx264", "medium", 20,
        extra_args=("-maxrate", "2800k", "-bufsize", "5600k"),
    ),
}


def get_profile(name: str) -> RenderProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown render profile '{name}'. Expected one of: {choices}") from exc
