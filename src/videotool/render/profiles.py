from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderProfile:
    name: str
    encoder: str
    preset: str | None
    crf: int | None
    extra_args: tuple[str, ...] = ()


# libx264 (CPU) profiles are wired end-to-end. h264_nvenc rides the same generic codec_args
# path (no CRF, quality via -cq in extra_args, no hwupload filter chain) so it needs no builder
# work; it is meant for cloud GPU runners (T4). VAAPI/AV1/HEVC still need -vaapi_device +
# hwupload chains the builder does not emit and stay rejected.
PROFILES = {
    "libx264-balanced": RenderProfile("libx264-balanced", "libx264", "medium", 20),
    "libx264-fast": RenderProfile("libx264-fast", "libx264", "veryfast", 23),
    # Same quality as balanced (medium/CRF20) with a VBV ceiling so a long video stays
    # under a size budget. Peaks cap at maxrate; the long-run average never exceeds it.
    "libx264-balanced-capped": RenderProfile(
        "libx264-balanced-capped", "libx264", "medium", 20,
        extra_args=("-maxrate", "2800k", "-bufsize", "5600k"),
    ),
    # GPU encode for cloud runners. VBR + -cq holds quality; the same VBV ceiling as the
    # capped x264 profile keeps a long video under the size budget. -preset p5 needs ffmpeg
    # >= 4.4 (the p1-p7 namespace); the cloud runner probes for it before selecting this.
    "h264_nvenc-capped": RenderProfile(
        "h264_nvenc-capped", "h264_nvenc", "p5", None,
        extra_args=("-rc", "vbr", "-cq", "23", "-maxrate", "2800k", "-bufsize", "5600k"),
    ),
    # Lower VBV ceiling for very long episodes: at 2800k a 2.6h render lands ~3.4 GB, over the
    # publish budget. Same quality knobs, ~2.5 Mbit/s average instead.
    "libx264-balanced-capped-2500k": RenderProfile(
        "libx264-balanced-capped-2500k", "libx264", "medium", 20,
        extra_args=("-maxrate", "2500k", "-bufsize", "5000k"),
    ),
    "h264_nvenc-capped-2500k": RenderProfile(
        "h264_nvenc-capped-2500k", "h264_nvenc", "p5", None,
        extra_args=("-rc", "vbr", "-cq", "23", "-maxrate", "2500k", "-bufsize", "5000k"),
    ),
}


def get_profile(name: str) -> RenderProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown render profile '{name}'. Expected one of: {choices}") from exc
