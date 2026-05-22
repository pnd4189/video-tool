---
phase: 5
title: "Offline AI Audio And Subtitle Pipeline"
status: in-progress
priority: P1
effort: "2-3d"
dependencies: [1, 2, 4]
---

# Phase 5: Offline AI Audio And Subtitle Pipeline

## Context Links

- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- auto-editor: https://github.com/WyattBlue/auto-editor

## Overview

Add offline transcript/subtitle generation and silence analysis that run acceptably on the target mini PC. Keep AI optional and adapter-based.

## Requirements

- Functional: generate SRT, transcript JSON, word/segment timestamps when available, silence ranges, cut suggestions.
- Non-functional: one AI job at a time by default, configurable model, no cloud dependency, graceful fallback when optional AI packages are missing.

## Architecture

```text
voice audio
  -> normalize analysis copy
  -> transcription adapter
  -> transcript segments
  -> SRT writer
  -> silence detector
  -> cut suggestion report
```

Adapters:
- `faster-whisper`: default first implementation for Python integration, CPU int8.
- `whisper.cpp`: optional later CLI adapter for CPU/Vulkan benchmark.
- FFmpeg silence filters: baseline silence detection without ML.

## Related Code Files

| Action | Path | Purpose | Test Impact |
|---|---|---|---|
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/ai/transcribe.py` | Adapter interface and result model | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/ai/faster_whisper_adapter.py` | Optional faster-whisper adapter | Optional integration |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/ai/whisper_cpp_adapter.py` | Optional CLI adapter | Optional integration |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/ai/subtitles.py` | SRT writer and caption chunks | Unit tests |
| Create | `/home/dung/VIBE_CODING/video-tool/src/videotool/ai/silence.py` | FFmpeg silence detection | Unit/integration |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_subtitles.py` | SRT tests | New |
| Create | `/home/dung/VIBE_CODING/video-tool/tests/test_silence_detection.py` | Silence tests | New |

## Implementation Steps

1. Add optional dependency group `ai` for `faster-whisper`; do not install by default.
2. Define `TranscriptSegment`, `TranscriptResult`, and `Transcriber` protocol.
3. Implement SRT writer with UTF-8 output, stable timestamps, and line wrapping.
4. Implement silence detection using FFmpeg filters first.
5. Implement cut suggestion report, not destructive auto-cut.
6. Implement `faster-whisper` adapter with model, device, compute type, language, beam size settings. Default model: `small`; allow `base` for fastest drafts.
7. Implement `whisper.cpp` adapter as CLI path/config only if user has binary/models installed.
8. Add CLI hooks in Phase 6: `transcribe`, `analyze-audio`, `render --with-subtitles`.
9. Add benchmark command design: record model, duration, real time factor, RAM note.

## Function Or Interface Checklist

- `Transcriber`
- `TranscriptSegment`
- `write_srt(transcript, path)`
- `detect_silence(audio_path, threshold, min_duration)`
- `write_cut_suggestions(silence_ranges, path)`
- `select_transcriber(config)`

## Test Scenario Matrix

| Scenario | Type | Expected |
|---|---|---|
| SRT timestamp formatting | Unit | valid `HH:MM:SS,mmm` |
| Vietnamese text | Unit | UTF-8 preserved |
| empty transcript | Unit | empty SRT or clear warning |
| silence detection on synthetic audio | Integration | expected silence ranges |
| AI package missing | Unit | clear optional dependency error |
| model path missing | Unit | clear model setup error |

## Dependency Map

- Depends on Phase 4 for audio extraction/probing.
- Feeds Phase 4 subtitle burn-in hook and Phase 8 YouTube package.

## Success Criteria

- [ ] Tool can produce `.srt` from a voice file with `faster-whisper` CPU int8.
- [x] Tool can produce silence/cut suggestion report without ML dependencies.
- [x] Missing optional AI dependencies fail with actionable instructions.
- [x] Subtitle writer handles Vietnamese text.
- [x] Render pipeline can consume generated SRT.

## Risk Assessment

- Risk: transcription too slow on current RAM. Mitigation: default to small/medium int8 and benchmark.
- Risk: bad auto-cuts harm final content. Mitigation: suggestions only in V1.
- Risk: optional dependencies complicate install. Mitigation: separate `ai` extra and clear doctor checks.

## Security Considerations

- Do not auto-download models without explicit command.
- Store model cache outside git.
- Never upload audio to external APIs in V1.
