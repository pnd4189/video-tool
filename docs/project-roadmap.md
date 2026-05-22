# Roadmap

Single source of truth for what's next, what's deferred, and what's explicitly out of scope. Update this file when a deferred item is requested or promoted to Now.

## Now (next session)

Wait for user to run the tool with real input (TTS voice + real music + storyboard), then react to feedback. Nothing else queued — no proactive feature work until that loop closes.

## Deferred (with reason)

These were considered and pushed out. Re-promote only if the reason no longer holds — do NOT silently re-propose.

| Item | Why deferred | Promote when |
|------|--------------|--------------|
| Workspace `.videotool/tmp/` auto-cleanup after successful render | YAGNI — current jobs leave <50MB; only matters at high job volume | User reports disk pressure OR runs >20 jobs without cleanup |
| Chapter auto-detect from silence gaps | Manual chapters in `job.yaml` are more accurate for audio stories; `detect_silence` already exists if needed | User asks to skip manual chapter authoring |
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

See `docs/project-changelog.md` for the dated record. The roadmap only carries the current cursor.
