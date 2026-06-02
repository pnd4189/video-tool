# Roadmap

Single source of truth for what's next, what's deferred, and what's explicitly out of scope. Update this file when a deferred item is requested or promoted to Now.

## Now (next session)

Run a real BÌNH THIÊN SÁCH tập end-to-end via `/make-video` (full tier: showwaves + subtitles +
chapters from transcript + templated description) and react to feedback — especially chapter-timestamp
drift (W1 ±5–15s) and long-audio whisper time. No other proactive feature work until that loop closes.

## Deferred (with reason)

These were considered and pushed out. Re-promote only if the reason no longer holds — do NOT silently re-propose.

| Item | Why deferred | Promote when |
|------|--------------|--------------|
| Workspace `.videotool/tmp/` auto-cleanup after successful render | YAGNI — current jobs leave <50MB; only matters at high job volume | User reports disk pressure OR runs >20 jobs without cleanup |
| Chapter auto-detect from silence gaps | Superseded: chapters now derived from the aligned transcript (W1) via `transcribe` → `chapters.json` | N/A (done differently) |
| W2 forced-alignment chapter precision (acoustic match of spoken "Chương N") | W1 (aligned-cue timing, ±5–15s) is free + robust; W2 is fragile on VN ASR mishears | W1 drift proves unacceptable on real uploads |
| Baked moving-icon progress bar | Sweezy-style bar is viewer-side (Chrome ext), not renderable; YouTube native chapters cover seeking | User wants an in-pixel indicator despite cosmetic-only value |
| Voice pre-normalization stage (before sidechain) | TTS output usually has consistent volume; sidechain ratio=8 is forgiving | User reports inconsistent ducking on real voice |
| Two-pass loudnorm (current is single-pass, ±1 LUFS drift possible) | Single-pass hits YouTube target close enough; doubles render time | User reports loudness rejection from YouTube |
| Loudness verification gate (fail render if measured LUFS off-target) | Package step already measures + reports; failing render is too aggressive | User asks for hard gate |
| GPU encode (NVENC/QSV/VAAPI) | Removed in /fix because broken on this AMD 760M iGPU and CPU is fast enough | User moves to a machine with working hwaccel AND CPU encode is too slow |

## Won't do (explicit out of scope)

These are NOT just deferred — they were ruled out. Do not implement without user reopening the question.

- **Cloud rendering** — local-first tool by design
- **Social upload automation** — out of scope per README
- **CapCut project compatibility** — out of scope per README
- **Full timeline editor / GUI beyond the queue shell** — CLI-first product
- **Semantic B-roll retrieval / automatic media selection** — deterministic storyboard mapping is the chosen model
- **Automatic model downloads (Whisper etc.)** — user supplies model path; never implicit network IO
- **Music tracks shorter than `target / MAX_PLAYS` (200 plays cap)** — user-actionable error instead; cap exists to prevent pathological filter graphs

## Recently shipped (anchor for changelog)

Render enhance tiers shipped on 2026-05-31. See `docs/project-changelog.md` for the dated record.
