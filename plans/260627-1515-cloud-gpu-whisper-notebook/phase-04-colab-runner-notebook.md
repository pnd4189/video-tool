---
phase: 4
title: "Colab runner notebook"
status: done
effort: "S"
---

# Phase 4: Colab runner notebook (BACKUP)

## Overview
Same core as Phase 3 but I/O via native `drive.mount` — simpler, used when Kaggle quota is spent.
The mounted Drive IS the filesystem, so no copy step; whisper reads voice in place and writes the 2
output files back to the same Drive folder.

## Requirements
- Functional: set `JOB_DIR="/content/drive/MyDrive/.../CHAP N"`, run cells → `captions.srt` +
  `chapters.json` written into `JOB_DIR/outputs/` on Drive.
- Non-functional: reuse `videotool_cloud.py` unchanged; only the I/O shim differs from Kaggle.

## Architecture
`from google.colab import drive; drive.mount('/content/drive')` → `run_whisper(JOB_DIR, ...)` operates
directly on the mounted path. Reading ~70MB voice over the mount is fine; outputs are tiny.

## Related Code Files
- Create: `Colab/colab_runner.ipynb`
- Use: `Colab/videotool_cloud.py` (Phase 2)

## Implementation Steps
1. Cell — mount: `drive.mount('/content/drive')`.
<!-- Updated: Validation Session 1 - WHISPER_MODEL=large-v3; install git+https; no HF token -->
2. Cell — install: fetch `videotool_cloud.py` (from the mounted `_VIDEOTOOL_SHARED/` or git);
   `videotool_cloud.setup()` (default `git+https://github.com/pnd4189/video-tool@<tag>`); assert
   `cuda.is_available()` (Colab T4).
3. Cell — input + run: `JOB_DIR="/content/drive/MyDrive/.../CHAP N"`;
   `run_whisper(JOB_DIR, model="large-v3", device="cuda", compute_type="float16")`.
4. Cell — confirm: list `JOB_DIR/outputs/` and print the first few SRT cues.

## Success Criteria
- [ ] From a mounted `JOB_DIR`, writes `captions.srt` (+ `chapters.json`) into the same Drive folder
- [ ] Uses `videotool_cloud.py` with no notebook-specific edits to the core
- [ ] GPU float16 used on Colab T4 (`large-v3`)

## Risk Assessment
- Colab idle disconnect on long audio → `large-v3` runs in minutes; acceptable.
- HF download: `large-v3` public, no token; per-account `HF_TOKEN` via Colab `userdata` only if rate-limited (deferred).
- Writing directly on the mount can be flaky for large files; here outputs are 2 small files, so low risk.
- Path differences (`MyDrive` vs shared drives) → document both in Phase 5.
