---
phase: 3
title: "Kaggle runner notebook"
status: done
effort: "M"
---

# Phase 3: Kaggle runner notebook (PRIMARY)

## Overview
Kaggle notebook (T4 GPU, 30h/week) that pulls only voice + script from a Drive path via rclone,
runs `videotool_cloud.run_whisper`, and pushes `captions.srt`/`chapters.json` back. Kaggle has no
Drive mount, so rclone + Secrets is the integration.

## Requirements
- Functional: set `JOB_REMOTE="gdrive:1. YOUTUBE AUDIO/.../CHAP N"`, run all cells → captions +
  chapters land in `JOB_REMOTE/outputs/` on Drive.
- Non-functional: transfer ≈ voice (~70MB) only; no 50-file gdown cap; GPU (float16) confirmed.

## Architecture
rclone remote `gdrive:` reconstructed at runtime from a Kaggle Secret holding the `rclone.conf`
body. Pull-filter to audio + `*_vi.txt`; run core; push the 2 output files. `kernel-metadata.json`
enables the GPU accelerator + internet.

## Related Code Files
- Create: `Colab/kaggle_runner.ipynb`
- Create: `Colab/kernel-metadata.json` (GPU + internet enabled; reference the one in `/home/dung/VIBE_CODING/2. COLAB`)
- Use: `Colab/videotool_cloud.py` (Phase 2)

## Implementation Steps
1. Cell — secrets + rclone: `from kaggle_secrets import UserSecretsClient`; write
   `UserSecretsClient().get_secret("RCLONE_CONF")` to `~/.config/rclone/rclone.conf`; `curl` install
   rclone; `rclone listremotes` sanity check.
2. Cell — install: fetch `videotool_cloud.py` (rclone-copy from `_VIDEOTOOL_SHARED/` or clone repo);
   `videotool_cloud.setup()` (defaults to `git+https://github.com/pnd4189/video-tool@<tag>`; pass a
   Drive-staged wheel path only if the repo is private); assert `cuda.is_available()`.
3. Cell — input: `JOB_REMOTE = "gdrive:.../CHAP N"`; `rclone copy "$JOB_REMOTE" /kaggle/working/job
   --include "*.mp3" --include "*.wav" --include "*.m4a" --include "*_vi.txt" --include "job.yaml"
   --include "_creative/**"` (NO Image/Video/Parallax/Music).
<!-- Updated: Validation Session 1 - WHISPER_MODEL=large-v3; install git+https; no HF token -->
4. Cell — run: `run_whisper("/kaggle/working/job", model=WHISPER_MODEL, device="cuda",
   compute_type="float16")` with `WHISPER_MODEL="large-v3"` (turbo dropped).
5. Cell — push back: `rclone copy /kaggle/working/job/outputs "$JOB_REMOTE/outputs"
   --include "captions.srt" --include "chapters.json"`; print remote listing to confirm.

## Success Criteria
- [ ] Fresh Kaggle session: from `JOB_REMOTE`, writes `captions.srt` (+ `chapters.json`) back to Drive
- [ ] Only audio + `*_vi.txt` transferred (verify rclone stats; no Image/ pulled)
- [ ] GPU float16 used (log shows CUDA), `large-v3` on 49-min audio finishes within session limit
- [ ] No gdown / 50-file errors

## Risk Assessment
- Secret name/format: document creating Kaggle Secret `RCLONE_CONF` = full rclone.conf text (incl. the
  `[gdrive]` token block). Covered in Phase 5 doc.
- rclone token expiry → refresh in the Secret; notebook fails fast on `listremotes`.
- Kaggle session GPU quota — `large-v3` on T4 runs in minutes, well under 9h/session.
- HF download: `large-v3` public, no token; if anonymous rate-limits bite, add `HF_TOKEN` as a Kaggle
  Secret (set once per Kaggle account) — deferred, not wired by default.
