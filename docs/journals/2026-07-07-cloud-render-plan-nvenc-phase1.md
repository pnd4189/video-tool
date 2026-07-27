# Cloud Render Plan + NVENC Phase 1 — Red Team Reshaped the Whole Checkpoint Design

**Date**: 2026-07-07 09:40
**Severity**: Medium (Phase 1 shipped + tested; cloud system planned, not built)
**Component**: Render profiles (`h264_nvenc-capped`), planned cloud render path (Colab/Kaggle), LLM orchestrator
**Status**: Phase 1 committed (`feat/nvenc-encoder-profile` b655256); Phases 2–4 planned + red-teamed, not implemented

## What Happened

User wants a second, parallel render system on Colab/Kaggle free tier as a hardware-risk backup for local `/make-video` (pain = heat + machine occupation, NOT speed). This reverses the 2026-06 "render stays local" decision — user-driven, justified: assets already live on Drive so there is no upload cost, and NVENC on a T4 sidesteps the "cloud CPU is slower than local" objection that killed the idea before.

Flow: brainstorm → plan (4 phases) → red-team → cook Phase 1.

Plan shape: everything new lives in `Colab/`; the ONLY shared-code touch is an additive NVENC profile. LLM orchestrator (`cloud_director.py`) replaces the local Claude-authoring steps (music_schedule, SFX cues, description, chapters) — Colab uses GLM coding plan, Kaggle a configurable free model.

## The Brutal Truth — Red Team Earned Its Keep

Three hostile reviewers (Security Adversary, Assumption Destroyer, Failure Mode Analyst) tore the plan apart with grep evidence. They found the **headline feature — resume-after-disconnect — was broken three compounding ways** in the original design:

1. **Checkpoint glob targeted the wrong path.** Clips live at `.videotool/tmp/clips/<preset>/scene-NNNN.mp4` (`services.py:189`), not flat `tmp/`. A `tmp/*.mp4` sync captures nothing → every disconnect re-renders from scene 0. The exact pain the plan existed to solve.
2. **Below 40 scenes there is no resume at all.** Resume only exists on the segmented path (`services.py:218`, `max_inline_scenes` default 40); a typical ≤40-scene episode renders as one ffmpeg call. Fix: cloud job.yaml sets `max_inline_scenes: 0` to force segmented.
3. **Size>0 completeness check trusts truncated clips.** `_is_complete` (`executor.py:107-108`) trusts any nonzero file; the `.part` atomic rename (`executor.py:48-50`) guards a local crash, NOT the lossy Drive round-trip. A clip half-uploaded to Drive gets welded into the final video, reported as success. And the "skip `*.part`" filter is wrong — the temp is `scene-NNNN.part.mp4` (still `.mp4`-suffixed).

13 findings accepted (3 Critical, 5 High, 3 Medium, 2 Low), 0 rejected — every one carried a file:line citation. Security cluster was right-sized DOWN to a solo-operator threat model (own Drive/Colab/keys, no second principal); the data-loss/correctness cluster kept full severity because those will actually bite.

Lesson reinforced: a plan that *sounds* right ("segmented render is already resumable, checkpoint is pure file sync") can be load-bearing-false against the code. The reviewers read `executor.py`/`services.py`/`segmented.py` directly and caught what the plan author (me) asserted from memory.

## Technical Details — Phase 1 (shipped)

`h264_nvenc-capped` profile: `("h264_nvenc", "p5", crf=None, extra_args=(-rc vbr -cq 23 -maxrate 2800k -bufsize 5600k))`. Rides the existing generic `codec_args()` — `crf=None` is skipped, `extra_args` appended — so NVENC needed zero builder work beyond widening `_reject_unsupported_profile` to accept the `h264_nvenc` prefix (AV1/HEVC/VAAPI still rejected; verified).

The subtle correctness point (red-team M9): `_reject_unsupported_profile` has ONE caller — the inline path. The segmented path (`segmented.py:81,109`) is ungated and is the one cloud actually uses. So tests assert the emitted encoder on BOTH inline `build_ffmpeg_command` and segmented `build_segmented_render` (scene-clip + full-tier mux re-encode), not just inline.

`-preset p5` needs ffmpeg ≥4.4 (the p1–p7 namespace); Phase 1 asserts the token so a version mismatch fails loud, and Phase 3's GPU probe will require ≥4.4 or fall back to a legacy preset name.

Suite: **193 passing** (4 new). Default `libx264-balanced` proven byte-unchanged. Not GPU-verified — no T4 session; deferred honestly to Phase 4.

## Open Threads

- GLM coding-plan ToS/quota for raw (non-coding-tool) API calls — verify in Phase 2.
- NVENC `-cq 23` vs the <2.5GB size cap — measure on a real long render in Phase 4.
- Real episode scene count — does a 45-min board actually clear 40 scenes? Determines how badly the inline-no-resume gap would have bitten.
