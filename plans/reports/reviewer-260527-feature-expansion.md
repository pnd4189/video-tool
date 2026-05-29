# Code Review — videotool feature expansion (5 phases)

Reviewer pass over working-tree diff. Tests: 66 pass (`.venv/bin/python -m pytest`). ruff/mypy not installed in venv (could not run static lint/type).

## Scope
- Changed: cli/commands.py, cli/main.py, cli/storyboard_commands.py, core/{job_spec,services,storyboard,timeline,validation}.py, render/{commands,executor}.py, docs/codebase-summary.md
- New: render/{audio_graph,segmented,video_filters}.py, ai/align_script.py, 4 test files
- ~292 LOC net (+ untracked new files)

## Acceptance criteria (a) — all met
- **P1 dB mixer**: AudioSpec present (voice_gain_db=0, music_gain_db=-18.0, duck=True, normalize_lufs=-14.0|None), `extra="forbid"`. audio_graph.build_audio_graph + audio_settings extracted. dB gains emit `volume={x}dB`; loudnorm uses `I={lufs:g}` (verified `-16` renders clean); duck adds sidechaincompress; normalize_lufs=None drops loudnorm. Threaded onto Timeline + compile_timeline. VERIFIED by test_audio_db_mixer (6 tests).
- **P2 storyboard**: natural_sort_key, discover_scene_images, build_even_split_storyboard (even split, last scene absorbs remainder, motion rotation via MOTION_CYCLE). auto_storyboard writes block preserving keys, warns on overwrite naming old count, re-validates via JobSpec.model_validate. VERIFIED.
- **P3 segmented**: SegmentedPlan + build_segmented_render (clip-per-scene + concat demuxer + audio-mux reusing P1 graph, `-c:v copy`). run_segmented resumable (skips clips on disk via `_is_complete`). services routes when `len(storyboard) > max_inline_scenes` (default 40). video_filters.py extracted. VERIFIED.
- **P4 script subtitle**: align_script.parse_script + align_script_to_transcript (proportional-to-char, monotonic, model-free). inputs.script added + validated. run_transcribe + CLI `--script`. VERIFIED.

## Regression (b) — no inline-path regression
- `_build_storyboard_command` still emits xfade (test_routing_inline_at_or_below_threshold asserts `xfade`; test_ffmpeg_commands:53 still green).
- build_ffmpeg_command structure unchanged except audio graph now from shared helper.
- Callers walked: build_render_plans (now delegates to `_compile_for_render`, same output), run_render (adds routing branch above inline, inline untouched), run_transcribe (script optional, default None = old behavior), compile_timeline (adds 4 audio fields with old-default values).
- **Behavioral note (minor, not a regression)**: no-music branch `-af` changed from bare `loudnorm=...` to `volume=0.0dB,loudnorm=...`. `volume=0.0dB` is a no-op; output identical. Default music gain changed `volume=0.5` → `volume=-18.0dB` — this is an *intentional* loudness change confirmed in plan decision #2, not a bug. ~`-18 dB` ≈ 0.126 linear vs old 0.5, so background music is markedly quieter than before. Confirm this is desired for any pre-existing jobs.

## Contracts (c) — backward compatible
- JobSpec: new `audio` + `render.max_inline_scenes` + `inputs.script` all have defaults; old job.yaml still loads under `extra="forbid"`. OK.
- Signatures: `build_render_plans` unchanged (public). `run_render` return type widened to include `list[SegmentedPlan]` — additive. `run_transcribe`/`commands.transcribe` gained trailing optional `script=None` — back-compat.
- CLI: `transcribe --script` optional; new `storyboard auto` subcommand. No removed commands.
- Internal-only rename `_codec_args/_metadata_args/_scene_filter/_is_image/_motion_expr` → public names in video_filters.py; no external callers. OK.

## Conventions (d) — consistent
- File naming kebab/snake matches repo. Helpers extracted to focused modules. `from __future__ import annotations` + dataclasses match existing style. SegmentedPlan mirrors CommandPlan shape.

## Lint / size (e)
- All new files < 200 lines. video_filters 68, audio_graph 58, align_script 68, segmented 106.
- **core/services.py = 299 lines** — pre-existing tech debt (was 254 pre-work), grew +45 here. NOT a fresh introduction; Phase-5 split candidate per task note. Not blocking.
- ruff/mypy unavailable in venv — static lint/type NOT verified. Recommend running in CI env.

## Edge cases (f)
- **Empty image folder**: build_even_split_storyboard raises ValueError("No images found"). OK.
- **Zero voice duration**: auto_storyboard guards `if not voice_duration or voice_duration <= 0: raise ValueError`. build_even_split itself unguarded but only reached via that guard or tests passing positive. OK.
- **align div-by-zero**: total_chars guarded by `max(1, len(sentence))`; total_speaking=0 yields offset 0 → `_time_at` returns first span start, no crash. Empty script / empty segments short-circuits to original. OK.
- **Monotonic SRT**: char_cursor non-decreasing → starts monotonic; `end=max(start,end)`; bounded by last span end. validate_srt on aligned output returns [] (test_aligned_result_writes_valid_srt). OK.
- **Concat codec consistency**: every clip uses identical codec_args(profile) + scale/crop/fps/yuv420p from scene_filter, so `-c:v copy` concat valid. Per-preset clips/concat dirs prevent resolution mixing. OK.
- **Resumability**: `_is_complete` = exists AND size>0. Skips done clips, mux always re-runs, concat list always rewritten. VERIFIED by test_run_segmented_skips_existing_clips.

## Findings

### blocker
- none.

### major
- none.

### minor
1. **Plan-phase reference in code comment** (repo rule violation). `render/segmented.py:39`: "The final mux reuses the **Phase 1** audio graph". Repo rules forbid plan phase numbers in code comments. Reword to e.g. "reuses the shared dB-mixer audio graph (build_audio_graph)". Only occurrence in source.
2. **CLI `--script` not path-validated**. run_transcribe joins `inputs.script` to job dir and run_validate checks its existence, but a CLI `--script` arg bypasses validation — a bad path surfaces as a raw `FileNotFoundError` from `parse_script` instead of a typed ValidationError. Low impact (interactive CLI), but inconsistent with the typed-error boundary elsewhere.

### nit
3. **`-shortest` + non-summing storyboard durations** (segmented mux): output length = min(concat video, voice-driven audio). For auto-gen boards durations sum to voice duration so fine; a hand-authored long board whose scene durations undershoot voice length would truncate audio. Same `duration=first` semantics as inline path, so consistent — documenting only.
4. **CLI `--script` relative path resolves to CWD** while `inputs.script` resolves to job dir. Standard CLI behavior; worth a one-line help note if users get confused.

## Positive
- Clean shared-helper extraction (audio_graph/video_filters) eliminates the prior duplicated filtergraph (commands.py:52-60 vs 94-100) without changing inline output.
- Resumable segmented render with per-scene + mux logs is a solid scaling design; `_run` seam refactor is tidy and well-tested via _RecordingExecutor.
- Strong TDD coverage: every new behavior + routing threshold + overwrite-warning + monotonic-SRT asserted. Generalization principle honored (synthetic naming-agnostic fixtures, no hardcoded Chap-1 patterns).
- type-tagged natural_sort_key avoids int/str comparison errors — nice.

## Plan task status
- Tasks #1–#4 (P1–P4) complete and verified by code + tests. Task #5 (docs refresh + integration verify) in_progress: docs/codebase-summary.md updated and accurate; end-to-end smoke (3-scene real + 50-scene dry-run) reported done by implementer. Recommend leader mark #5 complete after addressing minor #1.

## Recommended actions (priority order)
1. Fix minor #1 (strip "Phase 1" from segmented.py:39) — repo-rule compliance, 1-line.
2. Consider minor #2 (validate CLI `--script` path → typed error) — optional hardening.
3. Run ruff + mypy in a CI env (not installed locally) to close item (e).
4. Defer services.py split to Phase 5 cleanup as noted.

## Unresolved questions
- Music loudness drop (0.5 → -18 dB) is plan-confirmed; just flagging that any pre-existing job.yaml without an `audio:` block will now render music ~quieter. Intended? (Plan decision #2 says yes.)

**Status:** DONE_WITH_CONCERNS
**Summary:** All 5 phases meet acceptance criteria; 66 tests pass; inline path and public contracts preserved (additive only). One repo-rule violation (plan-phase ref in a code comment) plus two minor/nit hardening items.
**Concerns/Blockers:** Non-blocking — fix the "Phase 1" comment in render/segmented.py:39 (repo rule); ruff/mypy could not be run locally (not installed in venv).
