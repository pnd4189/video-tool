---
phase: 2
title: "Cloud director LLM orchestrator"
status: completed (code + local logic tests; live-LLM run pending user keys)
priority: P1
dependencies: []
---

# Phase 2: Cloud director LLM orchestrator

## Overview
`Colab/cloud_director.py`: replaces the local Claude-authored steps of `/make-video` with LLM API calls inside the notebook — authors job.yaml (music_schedule, SFX cues, description/recap, chapters fallback, mood-on-hint) with schema validation + retry.

## Requirements
- Functional: given a staged job folder (voice, Image/, Video/, Music/, `*_vi_qa.{txt,srt}`, `*_music_prompts.txt`, template, CTA folder), produce a complete audio-story job.yaml matching the current AGENTS.md flow, plus `outputs/captions.srt` copy and `chapters.json` (via `chapters-from-srt`, hand-fallback when <3 markers). Set `render.max_inline_scenes: 0` so the cloud render always takes the resumable segmented path (Phase 3 C3).
- Non-functional: provider-pluggable; API keys read from Secrets, never written to disk/Drive and never logged (redact — M11); conservative SFX rules (fewer cues than local Claude flow — only unambiguous keywords, respect density/CTA-region rules from AGENTS.md); every LLM output validated before use.
- **Idempotent (red-team H4):** if a pinned, already-validated job.yaml exists in the checkpoint (resume run), cloud_director is a NO-OP — it must not re-call the LLM. Authoring happens only on the first run; resume must not depend on the LLM being reachable or deterministic.

## Architecture
```
cloud_director.py
├─ providers.py-style abstraction (single file, small):
│    call_llm(messages, json_schema) →
│      "glm":    Anthropic-compatible endpoint (open.bigmodel.cn), key GLM_API_KEY
│      "gemini": generativelanguage.googleapis.com JSON mode, key GEMINI_API_KEY
│      "anthropic": api.anthropic.com (Haiku), key ANTHROPIC_API_KEY
│    provider chosen by env/Secrets present; Colab default glm, Kaggle default gemini
├─ deterministic pre-steps (NO LLM): init-job, sed policy/captions fixes,
│    storyboard auto --images-dir/--videos-dir, SRT copy, chapters-from-srt,
│    intro/ending/CTA detection (same filename heuristics as AGENTS.md)
├─ LLM tasks (each: prompt + strict JSON schema + validate + ≤2 retries):
│    1. music_schedule  — inputs: *_music_prompts.txt blocks, chapter seconds, track list
│    2. sfx cues        — inputs: captions.srt text w/ timestamps + sfx pack file list;
│                          output {file,start,gain_db}; enforce density/spacing/skip-regions
│                          in CODE (post-filter), not trust the model
│    3. description+recap — template placeholders {{CHAPTERS}}/{{RECAP_PREV}}/{{SUMMARY}}
│    4. chapters fallback — only when <3 "Chương" markers
└─ final gate: `videotool validate` PLUS cloud_director's own pre-render checks (red-team H8 —
     `videotool validate` does NOT cover these): assert `render.encoder ∈ PROFILES` (job_spec.py:259
     is a bare str, get_profile only runs at render time) and every SFX cue file exists + stays
     inside the job folder (validation.py candidates omit `enhance.sfx.cues`; run_sfx checks escape
     only AFTER render). On fail → feed error back, one repair round, else abort with clear report
     BEFORE any GPU time is spent.
```
Prompts live as string templates inside `cloud_director.py` (KISS; no prompt-file sprawl). SFX files copied from a Drive-staged sfx library mirror into `<job>/sfx/` (library lives locally at `~/.local/share/videotool/sfx/` — phase 3 stages it to `_VIDEOTOOL_SHARED/sfx/`).

## Related Code Files
- Create: `Colab/cloud_director.py`
- Modify: none in `src/` (constraint #2)
- Reference: `Colab/videotool_cloud.py` (`ensure_job_yaml`, `_harden_job_yaml` reuse)

## Implementation Steps
1. Provider abstraction + Secrets lookup (Colab `google.colab.userdata`, Kaggle `kaggle_secrets`), fail with actionable message when key missing. Keys stay in memory; redact from any log/exception (M11).
2. Idempotency guard first (H4): if pinned validated job.yaml present → return immediately, no LLM.
3. Deterministic pipeline steps ported from AGENTS.md standard flow; set `render.max_inline_scenes: 0`.
4. The 4 LLM tasks with JSON-schema outputs + code-side post-filters (SFX density/spacing/CTA-skip, music cue coverage/no-overlap, placeholder presence).
5. Pre-render gate: `videotool validate` + encoder-in-PROFILES + SFX-cue existence/escape checks (H8).
6. Dry-run mode (`--no-llm` stub responses) so pipeline is testable locally without keys; manual smoke test (notebook code, not CI suite).
7. Verify GLM coding-plan raw-API ToS/quota; if blocked, document and default Colab to Gemini too.

## Success Criteria
- [ ] Dry-run produces valid job.yaml (with `max_inline_scenes: 0`) passing `videotool validate` on a real staged episode locally.
- [ ] Live run with ≥1 provider authors music_schedule + SFX cues + description that pass code-side filters AND the encoder/SFX pre-render checks (H8).
- [ ] Resume run with a pinned job.yaml makes zero LLM calls (H4).
- [ ] No API key written to repo/Drive/job folder or any log (M11).

## Risk Assessment
- Cheap-model quality on Vietnamese homograph SFX filtering → mitigated by conservative keyword whitelist + code-side caps; accept fewer cues than local flow.
- GLM plan may forbid raw API use → fallback Gemini documented.
- Model drift/JSON malformed → schema validate + retry + abort-with-report, never render with junk cues.
- `videotool validate` is not a security boundary for LLM output (H8) → cloud_director owns encoder/SFX validation; don't assume the CLI catches a hallucinated encoder or escaping SFX path.
- Secrets: LLM keys stay in memory (never disk); the Kaggle rclone token unavoidably lives in `~/.config/rclone/rclone.conf` on the runner for the session (SA7) — scope it to the channel Drive subtree, treat as ephemeral runtime state, don't claim "zero secrets on disk".
