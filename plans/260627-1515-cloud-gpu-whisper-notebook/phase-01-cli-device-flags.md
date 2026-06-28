---
phase: 1
title: "CLI device flags"
status: done
effort: "S"
---

# Phase 1: CLI device flags + model-id passthrough

<!-- Updated: Validation Session 1 - model = large-v3 (turbo dropped); guard relaxation still required -->

## Overview
Let `transcribe` run on GPU with a HuggingFace model id. Today the CLI only takes a local model
path and hardcodes `cpu`/`int8`, and the adapter raises if the model isn't an existing path —
both block `--model large-v3 --device cuda`.

## Requirements
- Functional: `videotool transcribe <job> --model large-v3 --device cuda --compute-type float16`
  loads `WhisperModel("large-v3", device="cuda", compute_type="float16")`.
- Non-functional: defaults unchanged (`device=cpu`, `compute_type=int8`); an explicit local path that
  does not exist still errors (catch typos); `pytest -q` green (66+).

## Architecture
Thread two params through the existing chain:
`cli/main.py transcribe` → `cli/commands.py transcribe` → `core/services.run_transcribe`
→ `ai/faster_whisper_adapter.FasterWhisperTranscriber`. Relax the adapter's existence guard so a
bare model id (no path separator and not on disk) is treated as a HF model name passed straight to
`WhisperModel`; a value that looks like a path but is missing still raises.

## Related Code Files
- Modify: `src/videotool/cli/main.py` (add `--device`, `--compute-type` typer options, default cpu/int8)
- Modify: `src/videotool/cli/commands.py` (`transcribe(job_path, model, script, device, compute_type)`)
- Modify: `src/videotool/core/services.py` (`run_transcribe(..., device="cpu", compute_type="int8")` → pass to adapter)
- Modify: `src/videotool/ai/faster_whisper_adapter.py` (relax `model_path.exists()` guard for bare model ids)
- Create: `tests/test_transcribe_device_flags.py`

## Implementation Steps
1. Adapter: change guard to — treat `model` as a name when it has no path separator AND
   `not Path(model).exists()`; only raise `DependencyError` when it *looks like a path*
   (`os.sep`/`/` present) and is missing. Store `self.model_ref: str` (id or path string) and pass
   that to `WhisperModel(self.model_ref, device=..., compute_type=...)`.
2. `run_transcribe`: add `device="cpu"`, `compute_type="int8"` params; build
   `FasterWhisperTranscriber(model_path=model, device=device, compute_type=compute_type)` (keep
   accepting a str, stop forcing `Path(model)` so ids survive).
3. `commands.transcribe`: add `device`, `compute_type` params, forward to `run_transcribe`.
4. `main.py`: add `--device` (default `"cpu"`) and `--compute-type` (default `"int8"`) options; forward.
5. Test: monkeypatch `WhisperModel` (and/or `FasterWhisperTranscriber`) to capture init args; assert
   GPU flags propagate and that the default invocation still uses cpu/int8; assert a bogus
   `/no/such/model` path still raises.

## Success Criteria
- [ ] `transcribe --model large-v3 --device cuda --compute-type float16` constructs the model with those args (verified via monkeypatched test)
- [ ] Default `transcribe --model <local-path>` unchanged (cpu/int8)
- [ ] Missing explicit path still raises `DependencyError`
- [ ] `.venv/bin/python -m pytest -q` green (66+)

## Risk Assessment
- Guard relaxation could mask a typo'd model name as a silent HF download attempt → restrict the
  "name" branch to strings without a path separator, so `models/typo` still errors but `large-v3` passes.
- `large-v3` shorthand resolves to public `Systran/faster-whisper-large-v3` (no HF token); supported
  by `faster-whisper>=1.0` already pinned. No version bump needed (turbo dropped).
