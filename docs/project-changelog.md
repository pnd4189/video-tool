# Project Changelog

## 2026-05-20

- Added initial VideoTool V1 implementation: Python package, CLI workflow, job schema, timeline model, asset license metadata, FFmpeg render path, subtitle utilities, silence analysis, GUI queue shell, and YouTube package validator.
- Added examples, generated media fixture script, README, and focused pytest suite.
- Hardened review findings: no implicit AI model downloads, stricter validation at service boundaries, licensed-only asset index requirement, unknown preset failures, ffprobe error mapping, and stricter package artifact checks.
- Added storyboard planning and render support: parse `[Scene N]` prompt files, match `media/scene-###` assets, assign safe motion/transition presets, render multi-scene pan/zoom/crossfade videos, and burn SRT subtitles when requested.

## 2026-05-22

- Audio pipeline: replaced static `volume=0.18` music duck with `sidechaincompress` keyed off the voice bus; added explicit `loudnorm=I=-14:TP=-1:LRA=11` targeting the YouTube spec.
- Filter-graph safety: escaped `[`, `]`, `;` in `subtitles=` and other path-bearing filter args; added `-max_muxing_queue_size` to prevent stalls on long jobs.
- Removed broken VAAPI profiles; only `libx264-balanced` and `libx264-fast` remain (CPU encode, no iGPU dependency).
- Embedded video metadata (title/author/description) via `-metadata` and enriched the YouTube description writer with chapters, tags, and CTA.
- Packaging: codec accept-list `{h264, hevc, av1}`, integrated-LUFS measurement via `ebur128`, multi-thumbnail generator (5 candidates), manifest excludes itself, license walker now recurses into media subfolders.
- Subtitles: staged SRT into the workspace to dodge filter-graph escaping issues; normalized CRLF in `validate_srt`.
- Render executor: streaming `Popen` log + 6h timeout + SIGTERM on failure; replaced threaded `batch` with `ProcessPoolExecutor` for true parallel jobs.
- Music seamless loop: `prepare_seamless_music()` pre-renders the music track to exactly match voice duration using `acrossfade` between iterations + fade-out tail, eliminating the audible click at every loop boundary on long audio-story videos. Output is a FLAC inside `<job>/<temp_dir>/music-loop.flac`; the main render uses it instead of the raw music input.
- Added 4 regression tests covering trim/loop/error paths for the music loop module; full suite now at 43 passing.
