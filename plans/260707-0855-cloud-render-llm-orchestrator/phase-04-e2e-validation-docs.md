---
phase: 4
title: "E2E validation + docs"
status: in-progress (docs done; GPU E2E pending user Colab session)
priority: P2
dependencies: [3]
---

# Phase 4: E2E validation + docs

## Overview
Prove the whole thing on one real episode on Colab free tier, tune NVENC size cap, measure throughput honestly, document the parallel-system workflow.

## Requirements
- Functional: real audio-story episode (with SRT, music, CTA, b-roll) rendered fully on cloud; artifacts match local-flow contract (mp4, description.txt, captions.youtube.srt, chapters, quality-report).
- Non-functional: written go/no-go numbers (encode fps, wall time, file size) vs local render for the same episode.

## Related Code Files
- Create: `docs/cloud-render-setup.md` — platform setup, Secrets, provider choice, resume behavior, known limits (mirror style of `docs/cloud-gpu-whisper-setup.md`)
- Modify: `AGENTS.md` — short "Cloud render (parallel system)" pointer section + confirmed-decision entry (reversal of render-stays-local, dated)
- Modify: memory `cloud-gpu-next-step-local-render` — final state after validation

## Implementation Steps
1. Pick one already-published episode (known-good local output as reference).
2. Full Colab run; capture wall time per step, NVENC fps, output size.
3. Tune `-cq` (and maxrate if needed) until size <2.5GB with acceptable visual parity on spot-check vs local libx264 output.
4. Ear-audit SFX cue sample (montage method from memory `sfx-insertion-workflow`); compare description quality vs local Claude-authored.
5. Disconnect-resume drill on a real render — MUST use a **forced-segmented job** (`max_inline_scenes: 0`, per Phase 3 C3) so resume is actually exercised; confirm completed clips are not re-encoded and no LLM call fires on the resume run (H4). Plant a truncated size>0 clip on Drive and confirm restore rejects it (C2).
6. Verified-publish drill: simulate a write-back stall and confirm the checkpoint is retained, not deleted (H6). Kaggle smoke run (may be shorter episode) — secondary path.
7. Write docs + AGENTS.md pointer; run `pytest -q` + `videotool doctor` locally to confirm zero local regression.

## Success Criteria
- [ ] Episode E2E on Colab: only input = Drive path; artifacts complete + verified in `Output/`.
- [ ] Resume drill on a forced-segmented job passes (no re-encode of completed clips, no LLM call on resume); truncated-clip planted on Drive is rejected on restore.
- [ ] No-NVENC path aborts cleanly; verified-publish keeps checkpoint on simulated stall.
- [ ] Size <2.5GB; visual spot-check acceptable; SFX ear-audit pass; description usable.
- [ ] Throughput report written (cloud vs local wall time) — honest go/no-go on which platform is primary.
- [ ] `pytest -q` green locally; local render of a control job unchanged.

## Risk Assessment
- Filter-graph CPU bottleneck makes cloud slower than local wall-time → still acceptable per user (pain = machine occupation, not speed), but must be reported with numbers, not hidden.
- Free-tier GPU unavailability windows → document fallback order (Colab T4 → Kaggle T4 → wait), never silent CPU x264 full render without warning.
