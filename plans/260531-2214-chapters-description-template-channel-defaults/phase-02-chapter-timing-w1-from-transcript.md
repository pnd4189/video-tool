---
phase: 2
title: Chapter timing W1 from transcript
status: completed
priority: P2
effort: 3h
dependencies:
  - 1
---

# Phase 2: Chapter timing W1 from transcript

## Overview
Derive per-chapter timestamps (W1) from the **aligned transcript** and emit `outputs/chapters.json`.
Reuses the whisper+align pass that already runs for subtitles — one transcription feeds both
captions and chapters. Silence-aware (uses whisper speech spans), no acoustic forced-alignment.

## Requirements
- Functional: given a `*_vi.txt` with `Chương N: <title>` headings + the aligned `TranscriptResult`,
  produce ordered `[(start, "Chương N: <title>"), ...]`, first start forced to `00:00`.
- Functional: enforce YouTube chapter rules — ≥3 chapters and ≥10s between consecutive starts,
  else skip (no chapters.json) with a logged warning (do not emit an invalid chapter list).
- Non-functional: pure function, no whisper call of its own; deterministic given inputs.

## Architecture
- New `src/videotool/core/chapter_timing.py`:
  - `CHAPTER_RE = re.compile(r"^\s*Chương\s+\d+", re.IGNORECASE)` — matches a heading cue.
  - `derive_chapters(aligned: TranscriptResult) -> list[tuple[float, str]]`:
    filter `aligned.segments` whose `text` matches `CHAPTER_RE`; collect `(segment.start, text.strip())`.
  - `_enforce_youtube_rules(chapters) -> list[tuple[float,str]]`: sort by start; force `chapters[0]`
    start to `0.0`; drop/merge any entry whose start < prev+10s (keep first, skip too-close); if
    fewer than 3 remain → return `[]`.
- Why aligned segments carry headings: `parse_script` makes a heading line (no terminal punctuation)
  its own cue; `align_script_to_transcript` keeps cue `text` verbatim and assigns it a real `.start`
  mapped through whisper speech spans.
- Wire in `run_transcribe` (`core/services.py:164`): after `write_srt`, when `script_path` is set,
  build the aligned transcript explicitly (it already does for srt), call `derive_chapters`, and if
  non-empty write `outputs/chapters.json` as `[{"start": float, "title": str}, ...]` (UTF-8, indent=2).
  Refactor so the aligned transcript is computed once and shared by srt + chapters (DRY).

## Related Code Files
- Create: `src/videotool/core/chapter_timing.py`
- Create: `tests/test_chapter_timing.py`
- Modify: `src/videotool/core/services.py` (`run_transcribe` emits chapters.json)

## Implementation Steps
1. Write `tests/test_chapter_timing.py` (red):
   - Build a fake `TranscriptResult` with mixed segments (3 heading cues `Chương 11/12/13:` at
     0.0/600/1200s + non-heading cues) → assert 3 chapters, first start 0.0, titles preserved.
   - <3 headings → `[]`. Two headings <10s apart → the too-close one dropped.
2. Implement `chapter_timing.py` to pass tests.
3. Refactor `run_transcribe`: compute aligned transcript once; write srt; emit chapters.json when
   headings found. Add a focused test (fake transcriber) asserting chapters.json content + that no
   file is written when <3 headings.
4. Run full suite → green.

## Success Criteria
- [ ] `derive_chapters` returns ordered chapters, first = 00:00, ≥10s gaps, ≥3 or empty.
- [ ] `run_transcribe` writes `outputs/chapters.json` only when ≥3 valid headings exist.
- [ ] Subtitle output (captions.srt) unchanged (same aligned transcript reused).
- [ ] `pytest -q` passes.

## Risk Assessment
- W1 timing drifts ±5–15s if whisper drops long internal silences — acceptable for YouTube chapters;
  documented, not fixed.
- ASR text never matched against headings here (we match the script cue text, which is verbatim),
  so VN ASR mishears do not break chapter titles — only their `.start` comes from whisper timing.
- Headings whose vi.txt wording differs from `Chương N:` pattern → not detected; mitigated by a clear
  regex + warning when fewer than 3 found.
