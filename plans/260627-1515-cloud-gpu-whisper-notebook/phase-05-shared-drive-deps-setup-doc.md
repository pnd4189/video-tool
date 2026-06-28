---
phase: 5
title: "Shared Drive deps + setup doc"
status: done
effort: "S"
---

# Phase 5: Shared Drive deps + setup doc

## Overview
One-time scaffolding so a fresh notebook session is self-sufficient, plus the user-facing setup doc.
Whisper-only scope keeps `_VIDEOTOOL_SHARED` minimal now; overlays/sfx/fonts are deferred (only
needed when render moves to cloud).

## Requirements
- Functional: documented, repeatable path — fresh Kaggle/Colab session runs from a Drive job path
  with no manual fiddling beyond setting one variable.
- Non-functional: no secrets committed to the repo; doc lives under `docs/`.

<!-- Updated: Validation Session 1 - install git+https primary (wheel only if private); model large-v3 via runtime HF (no cache); HF token deferred -->

## Architecture
`gdrive:/_VIDEOTOOL_SHARED/` holds what the notebook fetches at runtime:
- `videotool_cloud.py`.
- (ONLY IF repo private) a built wheel for the offline install fallback. Default install is
  `git+https://github.com/pnd4189/video-tool@<tag>`, so the wheel is usually unnecessary.
- Model cache = NOT used — `large-v3` downloads from public HF at runtime each session (rclone-down
  from Drive isn't faster). No `models/` folder.
- (DEFERRED, documented as future) `overlays/`, `sfx/{dao-si,binh-thien}/`, `fonts/` — for when
  render runs on cloud; NOT used by whisper-only.

## Related Code Files
- Create: `docs/cloud-gpu-whisper-setup.md`
- Action (not code): create `gdrive:/_VIDEOTOOL_SHARED/`, upload `videotool_cloud.py` (+ wheel/model cache)

## Implementation Steps
1. Make the repo (or a tagged release) PUBLIC so `pip install git+https://...@<tag>` works on both
   platforms; tag a release (e.g. `v0.x`) for reproducible installs. ONLY if it must stay private:
   build the wheel (`python -m build`) and `rclone copy` it to `_VIDEOTOOL_SHARED/`.
2. `rclone copy videotool_cloud.py` to `_VIDEOTOOL_SHARED/`. (No model cache — runtime HF.)
3. Write `docs/cloud-gpu-whisper-setup.md`:
   - Repo-public vs private install (git+ tag vs Drive wheel).
   - How to get the rclone token and create Kaggle Secret `RCLONE_CONF` (full `rclone.conf` text) —
     set once per Kaggle account; same idea on Colab via `userdata`. Optional `HF_TOKEN` only if
     anonymous HF rate-limits appear (set once per account).
   - `JOB_REMOTE` (Kaggle) vs `JOB_DIR` (Colab) conventions + example paths.
   - Per-platform run steps; how the local render then consumes the returned `captions.srt`/`chapters.json`.
   - Quota-rotation note (same Drive folder, run either notebook).
   - The deferred `_SHARED` items (overlays/sfx/fonts) + when they become needed.
4. Cross-link the doc from `AGENTS.md` "Tech notes" (one line) so future sessions find it.

## Success Criteria
- [ ] `_VIDEOTOOL_SHARED/` exists on Drive with `videotool_cloud.py` (+ wheel only if repo private)
- [ ] `docs/cloud-gpu-whisper-setup.md` lets a new session run end-to-end without trial-and-error
- [ ] No tokens/secrets in the repo; AGENTS.md links the doc

## Risk Assessment
- Token rotation/expiry → doc covers refreshing the Kaggle Secret.
- Scope creep (uploading overlays/sfx now) → explicitly mark deferred; YAGNI for whisper-only.
