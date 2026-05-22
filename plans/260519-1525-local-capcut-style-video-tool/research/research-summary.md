---
title: "Research Summary"
status: final
created: "2026-05-19"
---

# Research Summary

## Summary

V1 should be a local FFmpeg composer, not a nonlinear editor clone. The winning pattern is "declarative job file -> timeline model -> FFmpeg graph -> YouTube package".

## CapCut Feature Lessons

Useful to copy conceptually:
- AI captions and transcript-assisted editing.
- Audio cleanup, background music, voice/music balancing.
- Template-driven repeatable production.
- Background removal and AI effects as later premium-style features.

Do not copy into V1:
- Full timeline UI.
- Cloud collaboration.
- AI image/video generation.
- Heavy visual effect marketplace.

Sources:
- CapCut AI editing: https://www.capcut.com/resource/ai-editing-the-capcut-way
- CapCut Pro help: https://www.capcut.com/help/capcut-pro
- CapCut credits: https://www.capcut.com/help/credit-types

## GitHub Repo Lessons

| Project | Lesson | Use In V1 |
|---|---|---|
| MoviePy | Friendly Python composition API, good mental model | Study API, avoid render-core dependency |
| Editly | Declarative JSON timeline and CLI/API split | Copy job/timeline philosophy |
| Remotion | Excellent motion/caption style with React | Defer; too much Node/React surface for V1 |
| auto-editor | Silence-based automatic edit decisions | Add cut suggestions, not destructive auto-cuts |
| PySceneDetect | Scene detection and transition detection | Later B-roll analysis helper |
| OpenTimelineIO | Durable timeline interchange model | Consider after V1 schema stabilizes |
| OpenShot/MLT | Mature NLE architecture | Reference only; too large to embed |

Sources:
- https://github.com/Zulko/moviepy
- https://github.com/mifi/editly
- https://github.com/remotion-dev/remotion
- https://github.com/WyattBlue/auto-editor
- https://github.com/Breakthrough/PySceneDetect
- https://github.com/AcademySoftwareFoundation/OpenTimelineIO
- https://github.com/OpenShot/openshot-qt
- https://github.com/mltframework/mlt

## Asset And License Sources

Recommended:
- YouTube Audio Library for safest music/SFX baseline.
- Pexels API for images/videos with permissive license.
- Pixabay API for images/videos/music/SFX, but still store license metadata.
- Freesound API only with license filtering and attribution tracking.

Rules:
- Store source URL, author, license, attribution requirement, commercial-use flag, content-ID risk.
- Never import random GitHub/Hugging Face assets without explicit license metadata.
- Hugging Face is better for models/datasets than production-ready stock asset packs.
- V1 uses manual import first. API downloaders are later extensions.

Sources:
- YouTube Audio Library: https://support.google.com/youtube/answer/3376882
- Pexels license: https://www.pexels.com/license/
- Pexels API: https://www.pexels.com/api/documentation/
- Pixabay license: https://pixabay.com/service/license-summary/
- Pixabay API: https://pixabay.com/api/docs/
- Freesound API: https://freesound.org/docs/api/overview.html

## FFmpeg And Output Standards

Use FFmpeg directly:
- `ffprobe` for duration, streams, dimensions, frame rate, audio sample rate.
- `overlay`, `scale`, `pad`, `crop`, `xfade`, `drawtext`, `subtitles` for video composition.
- `aloop`, `atrim`, `afade`, `sidechaincompress`, `amix`, `loudnorm` for music matching and audio mix.
- `-movflags +faststart`, H.264 High Profile, AAC-LC, yuv420p for YouTube-safe MP4.

Sources:
- FFmpeg filters: https://www.ffmpeg.org/ffmpeg-filters.html
- YouTube upload encoding: https://support.google.com/youtube/answer/1722171
- YouTube caption formats: https://support.google.com/youtube/answer/2734698
- YouTube thumbnails: https://support.google.com/youtube/answer/72431

## Offline AI Recommendation

V1 default path:
- `faster-whisper` CPU int8 for subtitle generation because it is simplest to integrate in Python.
- Default model: `small` for better Vietnamese subtitle quality; allow `base` for fastest drafts.
- Benchmark `whisper.cpp` CPU/Vulkan later as an optional alternative on Radeon 760M.
- Use FFmpeg silence analysis first; add auto-editor-like heuristics after baseline tests.

Avoid in V1:
- Video background removal.
- Local image/video generation.
- CLIP semantic B-roll search.

Sources:
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- auto-editor: https://github.com/WyattBlue/auto-editor

## Hardware Notes

Detected local machine:
- CPU: AMD Ryzen 5 7640HS, 6 cores / 12 threads.
- GPU: AMD Phoenix/Radeon 760M class iGPU.
- FFmpeg: 6.1.1, includes `libx264`, `libx265`, `libsvtav1`, `h264_vaapi`, `hevc_vaapi`, `av1_vaapi`.
- Visible RAM at planning time: about 14GiB. User plans to add 16GB RAM later.

Recommendation:
- Treat V1 as 16GB-safe.
- Render one job at a time by default.
- Add concurrency only for analysis steps, not simultaneous final renders.
- Benchmark VAAPI before making it default.
