---
title: 'make-video Plan 2: music-schedule per story mood + default SFX auto-burn'
description: ''
status: completed
priority: P2
branch: feat/make-video-srt-sub-audio-defaults
tags: []
blockedBy:
  - 260703-2248-make-video-srt-sub-audio-quality-defaults
blocks: []
created: '2026-07-03T16:30:57.032Z'
createdBy: 'ck:plan'
source: skill
---

# make-video Plan 2: music-schedule per story mood + default SFX auto-burn

## Overview

Plan 2 (feature) từ brainstorm `plans/reports/brainstorm-make-video-audio-subtitle-music-sfx-defaults-report.md`. Hai feature độc lập cho `/make-video`, kiến trúc "LLM phân loại → ghi cue vào job.yaml → tool render cue":

- **#4 Music theo đoạn truyện:** thêm `audio.music_schedule` (list cue `{track,start,end,gain_db?}`). Vắng → giữ concat-loop cũ (backward-compat). Bed lịch được pre-render thành 1 FLAC rồi thay music input — **KHÔNG đụng render graph**.
- **#3 SFX mặc định mức vừa (auto-burn):** thêm `enhance.sfx` (cues one-shot). Mix **hậu kỳ trên mp4 đã render** (`-c:v copy`, remux audio) — đúng phương pháp đã validate (memory `sfx-insertion-workflow`), **không luồn vào render graph** → giữ nguyên ổn định Plan 1. Beds (nhạc nền trận) ĐỂ SAU.

**Chốt từ user (2026-07-03):** SFX auto-burn không montage; mật độ 12–15 cue/45ph; palette (binh-thien/dao-si) LLM tự nhận theo thể loại; timing nhạc lấy từ marker "Chương" trong SRT (Chap 15 xác nhận có đủ).

**Kiến trúc offset CTA (nhất quán với subtitle):** cue music + sfx đều **narration-aligned**; tool shift `+intro_cta_seconds` khi stage/mix (LLM không cần biết CTA).

**Acceptance:** `pytest -q` xanh (thêm test music-schedule + sfx-mix); render smoke: nhạc đổi track đúng mốc chương + crossfade sạch; SFX rơi đúng từ hành động (sai số <~0.3s), không ducked, không đè CTA; job.yaml không có 2 field mới vẫn chạy y hệt Plan 1.

**Non-goals:** SFX beds/ambient; music theo scene (chỉ theo chương/khoảng thời gian); đổi loudnorm; UI.

**Depends on:** Plan 1 (`260703-2248-...`, đã code trên cùng branch) — dùng `chapters-from-srt`, `captions.srt` provided.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Music-schedule staging (audio.music_schedule)](./phase-01-music-schedule-staging-audio-music-schedule.md) | Completed |
| 2 | [SFX post-process mix (enhance.sfx)](./phase-02-sfx-post-process-mix-enhance-sfx.md) | Completed |
| 3 | [Workflow doc (make-video cue authoring)](./phase-03-workflow-doc-make-video-cue-authoring.md) | Completed |
| 4 | [Verify (pytest + render smoke)](./phase-04-verify-pytest-render-smoke.md) | Completed |

## Dependencies

<!-- Cross-plan dependencies -->
