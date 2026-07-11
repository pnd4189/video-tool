---
phase: 3
title: "Cloud runner notebooks + Drive checkpoint"
status: completed (code + local logic tests; GPU run pending phase 4)
priority: P1
dependencies: [1, 2]
---

# Phase 3: Cloud runner notebooks + Drive checkpoint

## Overview
Unified runner (`Colab/cloud_render_runner.py` + updated notebooks) chaining: setup → stage assets → cloud_director (first run only) → parallax-link → NVENC render with **correct, integrity-verified** segment checkpoints on Drive → sfx → verified publish to `Output/`. Colab primary, Kaggle secondary. Redesigned after red-team: the naive "rsync the temp dir" checkpoint was broken (wrong path, non-atomic, size-only trust) — see Red Team Hardening below.

## Requirements
- Functional: one cell run from a Drive folder path to `Output/`; rerun after disconnect resumes from last **verified** checkpointed segment with zero re-encode of completed clips and zero stale-clip reuse.
- Non-functional: never write to source asset folder except `Output/`; local `/make-video` untouched; free-tier friendly.

## Architecture (post-red-team)
```
runner flow (both platforms):
 1. videotool_cloud.setup(repo_ref=<pinned SHA>)   # NOT @main (L13)
 2. rclone copy Drive folder → /content/job         # rclone, NOT FUSE mount (H7)
 3. IF checkpoint exists on Drive:
      - rclone copy Drive checkpoint → /content/job/.videotool/tmp/clips/<preset>/  (C1 exact path)
      - restore the PINNED job.yaml from checkpoint (H4) — do NOT re-run cloud_director
      - ffprobe-verify each restored clip (duration ≈ scene slot); drop mismatches (C2)
    ELSE (first run):
      - cloud_director.run(job_dir)                 # phase 2, authors + validates job.yaml
      - set render.max_inline_scenes: 0             # FORCE segmented so every job resumes (C3)
      - if Parallax/ present → videotool parallax-link --clips-dir Parallax
      - PIN job.yaml → checkpoint dir on Drive (H4)
 4. probe GPU + NVENC + ffmpeg version (M10):
      - h264_nvenc present AND ffmpeg >= 4.4 (for -preset p5) → encoder h264_nvenc-capped
      - else → ABORT with clear message (H5), do NOT silently CPU-render.
        (CPU only if user opts in explicitly → capped profile + segmented, never mixed
         encoder into an existing checkpoint dir)
 5. videotool render --preset youtube-16x9
    + background thread every N min: rclone copy COMPLETED clips
      .videotool/tmp/clips/<preset>/scene-[0-9]*.mp4  (exclude scene-*.part.mp4)  (C1, C2)
      → Drive checkpoint, uploading to scene-NNNN.mp4.uploading then rename (atomic-ish) (C2)
 6. videotool sfx → package
 7. PUBLISH (H6): rclone copyto each artifact → Output/<name>.uploading → rename;
    re-list Output/ from a fresh rclone call and verify size>0 for every artifact
    BEFORE deleting the checkpoint dir. Stall/partial → keep checkpoint, report.
Kaggle deltas: rclone with KAGGLE Secret token (reuse kaggle_runner.ipynb list-form pattern);
sfx library staged once to gdrive:_VIDEOTOOL_SHARED/sfx/.
```

## Red Team Hardening (accepted findings)
- **C1 (Critical) — checkpoint path/glob:** clips live at `<job>/.videotool/tmp/clips/<preset>/scene-NNNN.mp4` (`services.py:189`, `segmented.py:67`), NOT flat `tmp/`. Sync/restore that exact nested tree. A flat `tmp/*.mp4` glob captures nothing → resume silently re-renders from scene 0.
- **C2 (Critical) — corrupt-clip reuse:** in-progress temp is `scene-NNNN.part.mp4` (keeps `.mp4` suffix, `executor.py:48-50`) so "skip `*.part`" fails and `*.mp4` grabs partials. `_is_complete` trusts `size>0` only (`executor.py:107-108`). Across a lossy Drive round-trip that accepts truncated clips. Fix: upload to `.uploading` temp + rename; on restore `ffprobe` each clip (duration ≈ scene) before trusting; sync only `scene-[0-9]*.mp4`.
- **C3 (Critical) — inline has no resume:** resume only exists when `len(storyboard) > max_inline_scenes` (default 40, `services.py:218`, `job_spec.py:264`); a typical ≤40-scene episode renders as one ffmpeg call with no checkpoint. Fix: cloud job.yaml sets `render.max_inline_scenes: 0` → always segmented. Consistent with AGENTS.md pitfall #5 ("don't force inline").
- **H4 (High) — stale/mixed clip reuse on rerun:** clips are index-addressed; re-running cloud_director on resume can change scene durations/order/encoder → old `scene-NNNN.mp4` reused by index → audio/video desync; nvenc+x264 clips mixed into `-c:v copy` concat. Fix: PIN job.yaml on first run to the checkpoint; on resume restore the pinned job.yaml and SKIP cloud_director + storyboard + LLM entirely (idempotent resume). Never switch encoder into an existing checkpoint.
- **H5 (High) — no-NVENC abort:** probe before render; abort with actionable message instead of silent uncapped `libx264-fast` that can cross the 6h `DEFAULT_TIMEOUT_SECONDS` (`executor.py:13`) and lose the whole session. CPU render only on explicit opt-in, capped + segmented.
- **H6 (High) — verified publish:** publish = temp-name + rename + fresh-listing size verify; keep checkpoint until persistence confirmed (memory `gdrive-mount-uploader-stall`: rclone VFS write-back can stall). Use `rclone copyto`, not FUSE flush timing.
- **H7 (High) — rclone not FUSE on Colab:** stage-in + checkpoint use `rclone copy` on Colab too (memory `gdrive-staging-use-rclone-not-cp`: FUSE ~60× slower). Native `drive.mount` only for convenience reads, never bulk I/O.
- **L12 — no shell injection:** new runner uses list-form `subprocess.run([...])`, never `shell=True` with an interpolated Drive path (also fixes Vietnamese folder names containing `'`). Mirror the whisper path (`videotool_cloud.py:187`).
- **L13 — supply chain:** `setup(repo_ref=<commit SHA>)` not `@main`; document the shared-Drive wheelhouse trust assumption; prefer pinned installs over `curl|sudo bash` on the key-bearing runner.

## Related Code Files
- Create: `Colab/cloud_render_runner.py`
- Modify: `Colab/colab_runner.ipynb`, `Colab/kaggle_runner.ipynb` (add "full render" section)
- Modify: `Colab/videotool_cloud.py` (staging/checkpoint/publish helpers, pinned repo_ref; keep whisper flow intact)
- Create (one-time op): `gdrive:_VIDEOTOOL_SHARED/sfx/{binh-thien,dao-si}` mirror
- Read-only refs: `src/videotool/core/services.py:189,218`, `render/executor.py:13,48-50,107-108`, `render/segmented.py:67`, `core/job_spec.py:264`

## Implementation Steps
1. Stage/publish helpers: rclone-based in + only-`Output/` out; verified publish (temp+rename+fresh-list); never delete/overwrite source.
2. Checkpoint sync thread targeting `clips/<preset>/scene-[0-9]*.mp4`; upload via `.uploading`+rename; exclude `*.part.mp4`.
3. Restore: copy nested clip tree back to identical path; ffprobe-verify each clip vs pinned storyboard duration; drop mismatches.
4. First-run vs resume branch: pin job.yaml; idempotent resume skips cloud_director/storyboard/LLM.
5. GPU + NVENC + ffmpeg-version probe with explicit abort (no silent CPU fallback).
6. Wire director → parallax-link → render → sfx → package → verified publish, list-form subprocess throughout; keys never logged to Drive (redact; ephemeral `/content` logs only).
7. Kaggle path: rclone via Secret; note rclone.conf lives on disk ephemerally (restated honestly, not "no keys on disk").
8. Update both notebooks; keep whisper cells working.

## Success Criteria
- [ ] Colab: full run from folder path → verified `Output/` artifacts; no manual step besides Run.
- [ ] Disconnect drill on a **>40-scene (forced-segmented)** job: rerun resumes, completed clips NOT re-rendered, ffprobe-verify passes, no stale-clip desync.
- [ ] Truncated-clip injection test: a size>0 but short clip on Drive is rejected on restore (not welded into output).
- [ ] No-NVENC path aborts with a clear message (does not silently CPU-render).
- [ ] Publish verified before checkpoint deletion; simulated write-back stall keeps checkpoint.
- [ ] Source Drive folder untouched except `Output/`; no API key in any Drive-synced log.
- [ ] Kaggle: same flow via rclone; documented secondary.

## Risk Assessment
- `max_inline_scenes: 0` forces per-scene clips even for short jobs → more small files to checkpoint; acceptable (they're the resume unit). Verify concat still `-c:v copy`-safe with uniform NVENC clips.
- ffprobe-verify per restored clip adds startup cost on resume → bounded by clip count; cheaper than re-encoding.
- Free-tier GPU roulette (T4 vs P100 vs none) → probe+abort covers it; document fallback order (T4 → reconnect → Kaggle T4 → explicit CPU opt-in).
