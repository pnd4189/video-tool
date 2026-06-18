# Project Changelog

## 2026-06-18

- Added Colab-offload 2.5D parallax path: new `/parallax-video` command + `videotool parallax-link <job> --clips-dir Parallax`, which swaps each image scene for a matching `Parallax/<image-stem>.mp4` clip at the data layer (missing clip → stays Ken Burns still). Render reuses the existing video loop+trim — no render-code change, no local torch. Distinct from the local-numpy `enhance.parallax`.
- Added `Colab/v4_depthflow_clips_colab.py`: DepthFlow GPU renders one loopable 1080p clip per still (clips-only, named by image stem) for manual transport into `Parallax/`.
- Fixed atmosphere/glow screen-blends to run in RGB (`gbrp`) — yuv420p blending tinted the whole frame magenta. Added local CC0 overlay library at `~/.cache/videotool/overlays/`. Suite now 149 passing.

## 2026-05-31 (later)

- Audio-story description+chapters: `transcribe` now derives YouTube chapter timestamps from the aligned transcript (W1) and writes `outputs/chapters.json` (`core/chapter_timing.py`); one whisper pass feeds both subtitles and chapters.
- Added template-driven description: `inputs.description_template` with `{{CHAPTERS}}`/`{{RECAP_PREV}}`/`{{SUMMARY}}` placeholders; `package` renders `outputs/description.txt` from it (chapters from chapters.json + agent-authored recap/summary). Non-template jobs unchanged.
- Added `project.recap_previous` field; lowered default `music_gain_db` −28 → −30 dB.
- Channel default for audio-story (`/make-video`): showwaves + subtitles on, progress bar off; auto-transcribe before render. Suite now 114 passing.

## 2026-05-31

- Added render enhance tiers: `enhance.tier: light|full`, preserving the fast light path while full tier burns SRT subtitles, adds bundled particle/grain overlay, progress bar, and optional waveform visualizer.
- Added `videotool render --enhance light|full` and optional `inputs.particle_overlay` override; bundled `dust.mp4` overlay source and license notes live under `src/videotool/assets/overlays/`.
- Verified full-tier smoke render with h264 1920x1080 video and AAC audio; full pytest suite now at 103 passing.

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
