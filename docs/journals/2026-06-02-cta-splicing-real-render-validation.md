# CTA Splicing Feature + Real-World Render Validation

**Date**: 2026-06-02 21:30
**Severity**: Medium (feature-complete, P2/P3 findings backlogged)
**Component**: Audio composition, chapter timing, overlay subtitle sizing
**Status**: Resolved (feature shipped; refinements noted for next phase)

## What Happened

Completed intro/outro CTA (call-to-action) audio splicing feature and validated the entire audio-story pipeline end-to-end with real Bình Thiên Sách Chap 3 content (93 min, 150 scenes, 2.0 GB output). Feature works. Output quality passes all gates. Found 2 fixable bugs and 2 UX refinements — all non-blocking.

## The Brutal Truth

We shipped a working feature without a real user run in hand. Chap 3 test run validated what we built but exposed doc and styling bugs that would have been obvious if we'd tested earlier. The whisper model path bug is embarrassing: the AGENTS.md doc claimed "offline ready" when the cache dir was **empty**. Had to download 145MB on-site. Subtitle sizing overwrote showwaves because we never burned captions alongside visualizer until today. These aren't design failures — they're validation gaps.

The good news: everything works once fixed. No architectural debt.

## Technical Details

### CTA Composition (cta_compose.py)
- `compose_voice()` normalizes intro/outro clips to 48 kHz stereo, concatenates via ffmpeg, returns durations.
- Chapter timing (`chapter_timing.py`) shifts all cues by `intro_seconds`; prepends synthetic "00:00 Giới thiệu" chapter (YouTube requires first marker at 00:00).
- Title cards auto-sized to intro/outro durations; scene images default to first/last storyboard frame.
- Music bed extended to cover spliced ends; no time overage.

### Chap 3 Output Quality (verified frame-by-frame)
- **h264 1920×1080, 5584.2s (93:04, matches narration + CTA + tail padding), aac 48kHz stereo, 2.0GB**
- **LUFS −14.2 dB** (target −14 ±1.5) — pass
- **10 chapters** auto-derived from transcript, correctly offset
- **Phụ đề (subtitles) render clearly** — but overlapped showwaves band (see P3 below)
- **showwaves visible** in FFmpeg filtergraph + confirmed in final output
- **music bed −30 dB** + sidechain ducking + loudnorm applied correctly
- **description.txt**: all 3 template placeholders ({{CHAPTERS}}, {{RECAP_PREV}}, {{SUMMARY}}) expanded, 0 holes, YouTube format correct

### Render Performance (wall-clock for 93-min video, libx264-balanced)
- Transcribe (whisper base, `base` model): 6 min
- Render (150 scenes, segmented path, mux re-encode for overlays): 76 min (24 min clips + 52 min mux)
- Package: 2 min
- **Total: 84 min for 93 min content** — reasonable on single CPU

### Test Suite
- 121 tests passing (up from 103 when CTA feature merged)
- cta_compose.py fully unit-tested (mono→stereo normalization, concat, duration extraction)

## What We Tried

1. **Whisper model not found**: Initial error `model path does not exist`. AGENTS.md claimed offline. Tried using bare "base" string as path — failed. Downloaded `Systran/faster-whisper-base` (~145 MB) to `~/.cache/videotool/models/faster-whisper-base`. Works now.
2. **Subtitle overlapping showwaves**: Burned captions without `PlayResX/Y` in force_style. libass defaulted to 384px canvas → scaled FontSize 42 to logical ×2.8 → chữ to, y≈866 (chồng showwaves band at y948+). Added `PlayResX=1920,PlayResY=1080` to force_style. Subtitles now pin to bottom 64px, clear of waveform.

## Root Cause Analysis

### P1 (Doc): "Offline ready" = Empty Cache Dir
AGENTS.md stated "AI extras (faster-whisper + deps) **are** installed; `base` model offline". In fact, the venv had the library but not the model weights. The doc should have been explicit: "weights must be downloaded on first run" OR we should have pre-baked them into CI/setup. We chose neither and then lied about it.

**Why it happened**: rapid feature iteration. We tested locally but didn't validate the gdrive staging workflow (which starts fresh) until Chap 3.

### P2 (UX): Whisper Model Path Not Intuitive
CLI expects `--model "$HOME/.cache/videotool/models/faster-whisper-base"` (a PATH), not a model alias. Users won't know this without reading code. The error message is cryptic. We should either:
- Use a bundled model alias in config (whisper-base → resolve to cache path), OR
- Auto-download on first run + cache, OR
- Document the exact invocation in AGENTS.md + make-video.md (current choice)

### P3 (Overlay): Subtitle Sizing Without PlayResX/Y
libass uses a 384×... default canvas when PlayResX/Y unspecified. We set absolute FontSize + Outline + MarginV without normalizing to the actual 1920×1080 video. This is a classic ASS subtitle bug; surprised it didn't surface earlier (because we hadn't overlaid showwaves + captions in the same output before).

## Lessons Learned

1. **"Offline ready" claims need venv + weights both verified.** Don't assume the library is enough.
2. **Test real user workflows before feature-branching.** Chap 3 was the first time we ran full stack with intro/outro + transcribe + overlays. Should have done a lightweight smoke test earlier (smaller audio, 5 scenes, 5 min render).
3. **ASS subtitle styling must always include PlayResX/Y** when targeting HD video. It's not negotiable.
4. **Chapters at 00:00 is a YouTube API hard rule.** The synthetic "Giới thiệu" chapter is load-bearing; easy to forget if not documented.

## Next Steps

1. **P1 (doc)**: Update `AGENTS.md` + `make-video.md` to show exact `--model` path; clarify "requires download on first run".
2. **P3 (subtitle sizing)**: Update `overlay_graph.py` to always set `PlayResX=1920,PlayResY=1080` in ASS force_style for 1920×1080 preset.
3. **P2/P4 (showwaves + chapter title clamping)**: Backlog refinements (visual mode choice, title length cap at 60 chars) — not critical for Chap 4+.
4. **P6 (template)**: Confirm gdrive template file has placeholders before next user run (currently only local staging had them).

---

**Status**: Feature complete. Output validated. Bugs identified and queued. Ready for Chap 4 production run with doc/styling fixes in place.
