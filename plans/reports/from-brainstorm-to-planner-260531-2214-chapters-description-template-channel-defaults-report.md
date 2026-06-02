---
title: "Audio-story description+chapters, channel defaults, music gain"
type: brainstorm-summary
date: 2026-05-31
status: approved-for-plan
branch: main
---

# Brainstorm — YouTube chapters + description template + channel defaults

## Problem statement
Audio-story tiên hiệp channel (Bình Thiên Sách). Each video = 1 tập = 10 chương, **one mp3 per tập**, Vietnamese TTS. Folder ships a `*_vi.txt` with Vietnamese chapter headings `Chương N: <title>`. Wants, per render:
1. `outputs/description.txt` rendered from the channel's fixed template (`_DESCRIPTION_TEMPLATE.txt`) with: chapter **timestamps**, a **recap of previous tập**, a **summary of this tập**.
2. Timestamps so YouTube auto-builds native chapter segments (paste description on upload).
3. **showwaves + subtitles as the default** for every audio-story job.
4. Lower default **music bed gain -28 → -30 dB**.
5. Asked for "cute-icon progress bar" like a referenced video.

## Hard truths established (scout-verified)
- **Referenced "custom progress bar" video = Sweezy Chrome extension** → viewer-side decoration, **creator cannot bake it**. Dropped. Use YouTube **native chapters** (interactive, seekable, free) via description timestamps instead. The other referenced video (b1Fo_M_tj6w) is literally YouTube's own "Add Chapters via timestamps" tutorial.
- Audio is **1 file/tập**, so no free per-file chapter boundaries.
- `align_script_to_transcript` (existing) is **proportional-by-char over whisper speech spans**, NOT acoustic forced alignment. Silence/intro-music excluded via whisper spans → more accurate than wall-clock proportional, robust, no ASR-mishearing risk.
- Subtitles default ON ⇒ whisper/align **already runs every job** → chapter timing comes free from the same pass (DRY).
- `project.chapters` (`ChapterSpec`) + `write_description` already exist but emit a generic format and don't read an external template.
- Current `music_gain_db` default = `-28.0` at `core/job_spec.py:87`.

## Decisions (user-confirmed)
1. **Chapter timestamps = W1**: read `.start` of chapter-heading cues from the **aligned transcript** (silence-aware, free, ~0 new accuracy code). W2 (forced ASR match, ±1-3s but fragile on VN numerals/names) explicitly deferred as future "precision mode".
2. **Recap + summary = Claude-authored** from vi.txt at `/make-video` time; tool stays LLM-free, accepts them as inputs. User reviews before upload.
3. **Progress bar dropped**; rely on YouTube native chapters.
4. **Channel default = showwaves + subtitles** (`enhance.visualizer/subtitles=true, progress_bar=false`); accept re-encode + whisper cost. Global `EnhanceSpec` default UNCHANGED (other users keep tier-light).
5. **music_gain_db default -28 → -30** (global; intended for all jobs).

## Approved design (4 pieces, 1 plan)

### Piece 1 — Chapter timing (W1)
- NEW `core/chapter_timing.py`: input = aligned `TranscriptResult` + vi.txt; filter cues matching `^Chương\s+\d+`; take aligned `.start` per heading → `[(start, title)]`.
- Enforce YouTube rules: first = `00:00`, gaps ≥10s, ≥3 chapters (clamp/merge if violated).
- Wire into `run_transcribe`: after align, write `outputs/chapters.json`. One whisper pass feeds subtitles + chapters.

### Piece 2 — Description template renderer
- KISS placeholder substitution. User inserts 3 tokens once into `_DESCRIPTION_TEMPLATE.txt`: `{{CHAPTERS}}`, `{{RECAP_PREV}}`, `{{SUMMARY}}`.
- Tool reads template → `str.replace` → `outputs/description.txt`. Empty placeholders → blank.
- `job_spec`: add `inputs.description_template: Path|None`, `project.recap_previous: str`; reuse `project.description` for this-tập summary; `inputs.script` already exists for vi.txt.
- `package/youtube.py`: add template-render path; keep existing `write_description` for non-template jobs (back-compat). `{{CHAPTERS}}` sourced from `chapters.json` when present, else `project.chapters`.

### Piece 3 — Channel defaults
- Do NOT change global `EnhanceSpec` defaults.
- `/make-video` (skill) + AGENTS.md: seed `enhance:{visualizer:true, subtitles:true, progress_bar:false}`, set `inputs.description_template` + `inputs.script`. Subtitles ON ⇒ orchestration runs `transcribe` before `render` (auto when captions.srt missing).

### Piece 4 — Music gain default
- `core/job_spec.py:87` `-28.0 → -30.0` + update comment. Update audio-graph snapshot tests expecting `-28`.

## Touchpoints
`core/chapter_timing.py` (new) · `core/services.py` (transcribe→chapters.json, package→template render) · `package/youtube.py` (template renderer) · `core/job_spec.py` (fields + music -30) · `cli` · `AGENTS.md` · skill `make-video`.

## Risks
- W1 timing drifts if whisper drops unusually long internal silences (±5-15s — acceptable for chapters).
- Long-audio whisper = slow (accepted).
- VN ASR mis-hears proper nouns → mitigated: subtitles use vi.txt wording via align; only timing is whisper's.
- Global music -30 affects all jobs (intended).

## Acceptance criteria
1. Tiên hiệp job via `/make-video` → mp4 (showwaves + burned subtitles) + `outputs/description.txt` from template, with 10-chapter timestamp block (first 00:00, ≥10s gaps), recap-prev + summary-this filled.
2. Description pasted on YouTube → native chapters render.
3. Music bed at -30 dB default.
4. Other (light) jobs unchanged except global music -30.

## Out of scope
Sweezy-style viewer progress bar; baked moving-icon indicator; W2 forced-alignment precision mode; auto-detecting chapters from raw audio; tool-side LLM summary generation.

## Open questions
- Exact placeholder names / which template sections host recap vs summary — confirm during plan against the real `_DESCRIPTION_TEMPLATE.txt` edits.
- `chapters.json` schema (list of {start,title}) — finalize in plan.
- Whether `/make-video` should auto-run transcribe silently or prompt when whisper is slow.
