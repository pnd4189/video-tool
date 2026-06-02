---
phase: 2
title: "Whisper sub-from-txt re-enable"
status: done
priority: P1
effort: "3-5h"
dependencies: [1]
---

# Phase 2: Whisper sub-from-txt re-enable

## Overview
Make "fast subtitles from the existing story txt" actually work. The chain is already coded (`run_transcribe` → `align_script_to_transcript` → `write_srt`); this phase installs the `ai` extra, verifies the path end-to-end, and makes the polished txt the timing source — Whisper supplies only timing, the txt supplies the words.

## Requirements
- Functional: `videotool transcribe <job> --model <m> [--script story.txt]` writes `outputs/captions.srt` whose cue **text** equals the script sentences, **timing** derived from audio via Whisper, cues monotonic + bounded.
- Functional: when `inputs.script` is set, it auto-drives alignment (already wired at `services.py:160`); confirm + test.
- Non-functional: unit tests must not require the Whisper model (mock the transcriber). Real model only in Phase 4 smoke.

## Architecture
- `pyproject.toml:19` already declares `ai = ["faster-whisper>=1.0"]`. Install into `.venv` (`pip install -e '.[ai]'`).
- `ai/faster_whisper_adapter.py` (`FasterWhisperTranscriber`) is the real adapter; keep as-is unless smoke reveals API drift.
- Timing source = txt: `align_script_to_transcript` already slices the whisper speaking-span proportionally to sentence char length → real txt words land on real timestamps. No code change expected, only verification + a focused test using a fake transcript.
- VN accuracy of Whisper is irrelevant (its text is discarded); only its segment **start/end** spans matter.

## Related Code Files
- Modify: `.venv` (install `.[ai]` extra) — environment, not source
- Verify/Modify (only if smoke needs): `src/videotool/ai/faster_whisper_adapter.py`, `src/videotool/ai/transcribe.py`
- Modify: `src/videotool/core/services.py` (only if `inputs.script` wiring needs a tier-full default; keep minimal)
- Create: `tests/test_caption_from_script.py`

## Implementation Steps
1. **Test first:** in `test_caption_from_script.py`, feed a hand-made `TranscriptResult` (3 fake whisper segments with known spans) + a 5-sentence script into `align_script_to_transcript`; assert output cues == the 5 sentences, ordered, non-overlapping, bounded by the whisper span. (Extends existing `test_align_script.py`; asserts the *text-from-script, timing-from-whisper* contract explicitly.)
2. Install `ai` extra into venv: `.venv/bin/pip install -e '.[ai]'`. Run `.venv/bin/videotool doctor` to confirm import.
3. Run `run_transcribe` against the repo's sample/fixture audio (or a short generated clip) + a tiny txt to confirm SRT is written and parses via `validate_srt`.
4. Confirm `services.py:160` script-driven alignment fires when `inputs.script` set; add a test asserting the SRT cue count == script sentence count for a fixture.
5. Keep `captions.mode` default `off` for light; tier-full will set `srt-and-burn` in Phase 3. No behavior change for existing jobs.

## Success Criteria
- [ ] `.venv` imports `faster_whisper`; `doctor` clean — DEFERRED to Phase 4 smoke (keeps .venv clean per 2026-05-28 decision; not needed for tier-light demo; all unit tests mock the transcriber)
- [x] caption SRT text == script sentences, timing from whisper span, monotonic + bounded (test) — `test_transcribe_cli.py` + `test_align_script.py`
- [x] `inputs.script` auto-drives alignment (wired `services.run_transcribe`; CLI `--script` path locked by `test_transcribe_applies_script_alignment`)
- [x] existing `test_align_script.py` + `test_subtitles.py` still green (90 passed)
- [x] tier-light install loads package without ai extra (`test_importing_videotool_does_not_pull_faster_whisper`)

## Implementation Notes (done 2026-05-31)
- Infra was already coded (adapter lazy-imports `faster_whisper` only inside `transcribe()`; CLI `transcribe --model --script`; `_run_guarded` maps `DependencyError`→exit 1). No source change needed — added `tests/test_transcribe_cli.py` (4 tests) to lock the end-to-end contract with a stubbed transcriber.
- `ai` extra install + real-model smoke moved to Phase 4.

## Risk Assessment
- Risk: `faster-whisper` pulls heavy deps (ctranslate2/onnxruntime) and may need a specific model download. Mitigation: unit tests mock the transcriber; document model fetch in Phase 4 smoke only.
- Risk: very long audio (1h45) → whisper slow / memory. Mitigation: timing-only; **default model `base`** (confirmed — balance speed/timing); expose `--model` to override. Benchmark in Phase 4. <!-- Updated: Validation Session 1 - default whisper model = base -->
- Risk: align drifts over long files if whisper drops long silences. Mitigation: align already walks per-segment spans (skips gaps); acceptable for burned subs. Note as smoke check.
