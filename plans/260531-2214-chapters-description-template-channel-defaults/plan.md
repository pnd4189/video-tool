---
title: 'Audio-story chapters, description template, channel defaults'
description: >-
  Whisper-timeline chapter timestamps (W1) + template-driven YouTube description
  (recap/summary/chapters) + channel defaults (showwaves+subtitles, no progress
  bar) + music bed -30dB. TDD where existing behavior changes.
status: completed
priority: P2
branch: main
tags:
  - feature
  - packaging
  - chapters
  - description
  - whisper
  - audio
blockedBy: []
blocks: []
created: '2026-05-31T15:18:45.771Z'
createdBy: 'ck:plan'
source: skill
---

# Audio-story chapters, description template, channel defaults

## Overview

Channel = audio truyện tiên hiệp (Bình Thiên Sách). 1 video = 1 tập = 10 chương, 1 mp3/tập,
voice tiếng Việt, kèm `*_vi.txt` có heading `Chương N: <title>`. Mục tiêu: sau render, ngoài mp4
còn xuất `description.txt` đúng template kênh, có **timestamp 10 chương** (YouTube tự chia chương),
**recap tập trước + tóm tắt tập này**. Đồng thời chuẩn hóa default kênh = **showwaves + phụ đề,
bỏ progress bar**, và hạ **nhạc nền −28→−30 dB**.

Nguồn brainstorm (đã duyệt): `plans/reports/from-brainstorm-to-planner-260531-2214-chapters-description-template-channel-defaults-report.md`

Chốt thiết kế: **W1** — mốc chương lấy từ **aligned transcript** (`align_script_to_transcript` đã
chạy sẵn cho phụ đề; silence-aware; 1 lần whisper nuôi cả sub + chương). Recap/summary do **agent
(Claude) soạn từ vi.txt**, tool không nhúng LLM (chỉ render template).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Music gain default -30](./phase-01-music-gain-default-30.md) | Completed |
| 2 | [Chapter timing W1 from transcript](./phase-02-chapter-timing-w1-from-transcript.md) | Completed |
| 3 | [Description template renderer](./phase-03-description-template-renderer.md) | Completed |
| 4 | [Channel defaults and docs](./phase-04-channel-defaults-and-docs.md) | Completed |

## Key architecture facts (verified)

- `AudioSpec.music_gain_db` default `-28.0` at `core/job_spec.py:87`. Tests assert `-28.0` at
  `tests/test_audio_db_mixer.py:40` + `tests/test_segmented_render.py:148`.
- `align_script_to_transcript` (`ai/align_script.py`) re-times script cues onto whisper speech
  spans by char proportion; a chapter heading (no terminal punct) becomes ONE cue → its aligned
  `.start` = chapter start. `TranscriptSegment(start,end,text)` / `TranscriptResult(language,segments)`.
- `run_transcribe` (`core/services.py:164`) already produces raw + (when `inputs.script` set) aligned
  transcript and writes `outputs/captions.srt`. Hook chapters.json emit here.
- `run_package` (`core/services.py`) builds `chapters` from `job.project.chapters` and calls
  `write_description` (`package/youtube.py:96`) with a generic format — extend, keep back-compat.
- `ConfigDict(extra="forbid")` on specs → new fields additive-safe.
- make-video command lives at `.claude/commands/make-video.md` (+ `.gemini/commands/make-video.toml`);
  AGENTS.md == CLAUDE.md (symlinked).

## Dependencies

- Phase 3 reads `outputs/chapters.json` from Phase 2 → 3 blockedBy 2.
- Phase 4 documents/seeds behavior from 1+2+3 → 4 blockedBy 1,2,3.
- Phase 1 independent (do first: isolated, locks regression).
- Builds on `260531-1648-render-enhance-overlay-tier` (done): enhance tier + subtitles burn exist.

## Validation Log

### Verification Results (Standard tier — Fact Checker + Contract Verifier)
- Claims checked: 11 | Verified: 11 | Failed: 0 | Unverified: 0
- Evidence: `music_gain_db=-28.0` job_spec.py:87 ✓; test asserts -28 at test_audio_db_mixer.py:40 + test_segmented_render.py:148 ✓; `align_script_to_transcript` + `parse_script` heading-as-cue ✓; `run_transcribe` services.py:164 builds raw+aligned ✓; `TranscriptSegment(start,end,text)` ✓; `_format_chapter_timestamp` youtube.py:125 + `write_srt` subtitles.py:22 ✓; validation.py candidate pattern (intro/ending/particle/script) ✓; make-video at .claude/commands/make-video.md ✓.
- Bonus: vi.txt headings are blank-line-separated → `parse_script` yields a clean heading cue ("Chương N: <title>"), so chapter titles are clean and W1 start times map correctly. No title/prose merge risk for this corpus.

### Validation Session 1 — decisions confirmed
1. **Placeholders** = `{{CHAPTERS}}` `{{RECAP_PREV}}` `{{SUMMARY}}` (user inserts into template once; literal replace). → Phase 3.
2. **No spoken intro/recap before chương đầu** → first chapter forced to `00:00` is correct; no "Giới thiệu" marker needed. → Phase 2.
3. **`{{RECAP_PREV}}` = NEW template section** ("TÓM TẮT TẬP TRƯỚC"); existing "TÓM TẮT TẬP" section hosts `{{SUMMARY}}` (this tập). `project.recap_previous` → RECAP_PREV; `project.description` → SUMMARY. → Phase 3.
4. **Auto-transcribe runs automatically** before render when subtitles on + srt missing, printing an expected-time warning (whisper slow on long audio); non-blocking. → Phase 4.

### Whole-Plan Consistency Sweep
Re-read plan.md + 4 phases. Decisions match existing plan content (tokens already named in Phase 3; first=00:00 already in Phase 2; auto-transcribe-with-notice already in Phase 4). Added field→placeholder mapping to Phase 3. No stale terms, no contradictions, no superseded assumptions. Zero unresolved contradictions.
