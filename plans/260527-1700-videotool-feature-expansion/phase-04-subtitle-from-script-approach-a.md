---
phase: 4
title: "Subtitle from script (approach A)"
status: done
priority: P2
effort: "1d"
dependencies: []
---

# Phase 4: Subtitle from script (approach A)

## Overview

Build subtitles from the polished script (`…_translated_qa.txt`) instead of
trusting raw ASR text. Approach A: faster-whisper provides the *timing* (segment
start/end as the clock); the SRT *text* is overwritten with the exact script
sentences so the Hán-Việt wording is preserved. No new dependency (reuse existing
faster-whisper + `ai/subtitles.py`).

Script format (verified): plain prose, sentences/paragraphs separated by blank
lines; first line is the chapter title (`Chương 1: …`).

## Requirements

- Functional:
  - `videotool transcribe JOB --script FILE` aligns and writes
    `outputs/captions.srt` using the script's wording with whisper timestamps.
  - Without `--script`, behavior is unchanged (plain whisper SRT).
  - Output SRT: monotonic timestamps, ≤2 lines / ~42 chars per cue (reuse
    `subtitles.segment_to_srt` wrapping), passes `validate_srt`.
- Non-functional: new `ai/align_script.py` <200 lines; pure functions
  (parse + align) testable without a real model.

## Architecture

- `ai/align_script.py`:
  - `parse_script(path) -> list[str]` — split into sentence-ish cues: paragraphs
    on blank lines, then sentences on `. ! ? …` boundaries (keep Vietnamese
    punctuation). Drop empty lines; keep order. **Generic prose only** — no
    `Chương N:`/heading special-casing, no filename assumptions; a title line is
    just the first cue. Must work on any plain-text script, not only the sample.
  - `align_script_to_transcript(script_sentences, transcript: TranscriptResult)
    -> TranscriptResult` — use whisper segment time spans as the clock; distribute
    script sentences across the timed segments. Strategy: walk segments in order,
    assign script sentences proportionally to each segment's duration / by
    cumulative character length, re-anchoring so cue start/end stay monotonic and
    bounded by the whisper span. Returns a new `TranscriptResult` whose segments
    carry script text + whisper timing.
- `core/services.py`: `run_transcribe(job_path, model, script: Path | None = None)`
  — after `transcriber.transcribe(...)`, if `script` given, `parse_script` +
  `align_script_to_transcript`, then `write_srt`. Keep `write_srt` output path
  `outputs/captions.srt`.
- `core/job_spec.py`: add `inputs.script: Path | None = None` (so the job can
  record the script; `--script` CLI flag overrides/supplies it). `validate_job_paths`
  should treat it like other input paths (must resolve under root if set).
- `cli/commands.py` + `cli/main.py`: add `--script` option to `transcribe`,
  threading to `run_transcribe`.

## Related Code Files

- Create: `src/videotool/ai/align_script.py`
- Create: `tests/test_align_script.py`
- Modify: `src/videotool/core/services.py` (run_transcribe signature + alignment)
- Modify: `src/videotool/core/job_spec.py` (`inputs.script`)
- Modify: `src/videotool/core/validation.py` (validate script path if present)
- Modify: `src/videotool/cli/commands.py`, `src/videotool/cli/main.py` (`--script`)

## Implementation Steps

1. **TDD (red)** in `tests/test_align_script.py`:
   - `parse_script` on a multi-paragraph sample → ordered list of non-empty
     sentence cues; chapter-title line handled (kept as first cue).
   - `align_script_to_transcript` with a synthetic `TranscriptResult` (e.g. 3
     timed segments) + 6 script sentences → returns segments with script text,
     monotonic non-overlapping timestamps within the original span, covering all
     sentences.
   - End-to-end-ish: feed the aligned result through `write_srt`, then
     `validate_srt` returns `[]`.
2. Implement `ai/align_script.py` (parse + align).
3. Add `inputs.script` to `JobSpec`; validate path in `validation.py`.
4. Thread `script` through `run_transcribe` + CLI `--script`.
5. Full suite green.

## Success Criteria

- [ ] `videotool transcribe Chap1/job.yaml --model … --script …_translated_qa.txt`
      writes `outputs/captions.srt` using exact script wording, monotonic
      timestamps, `validate_srt == []`.
- [ ] Plain `transcribe` (no `--script`) output unchanged; existing
      `test_subtitles.py` green.
- [ ] Alignment is deterministic and model-free in unit tests (no model download).

## Risk Assessment

- Drift over 107 min (approach A): sentence↔segment mapping can skew if ASR
  segment count diverges from script sentence count. Mitigation: re-anchor on
  whisper segment boundaries (segments are the clock) and distribute by char
  length within a segment; if sentence count ≫ segment count, split a segment's
  span proportionally. Heavier forced aligner (aeneas, approach B) is the
  documented fallback upgrade, out of scope here.
- Script sentence splitting on Vietnamese punctuation: keep simple regex; over-
  splitting only yields shorter cues (acceptable), never wrong wording.
