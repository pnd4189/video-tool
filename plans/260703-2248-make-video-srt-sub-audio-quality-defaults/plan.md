---
title: >-
  make-video quick-wins: provided-SRT, no-mood default, WAV-first, yellow
  audio-story subs, AAC 256k
description: ''
status: completed
priority: P2
branch: main
tags: []
blockedBy: []
blocks: []
created: '2026-07-03T15:52:42.784Z'
createdBy: 'ck:plan'
source: skill
---

# make-video quick-wins: provided-SRT, no-mood default, WAV-first, yellow audio-story subs, AAC 256k

## Overview

Plan 1 (quick-wins) từ brainstorm report `plans/reports/brainstorm-make-video-audio-subtitle-music-sfx-defaults-report.md`. 5 thay đổi default cho `/make-video`, rủi ro thấp, chạm ít code. KHÔNG bao gồm Plan 2 (SFX auto-burn + music-schedule).

**5 việc:**
1. Bỏ whisper khỏi flow mặc định `/make-video` — dùng SRT user cấp; thêm `videotool chapters-from-srt` sinh `chapters.json` từ marker "Chương NNN:" (SRT Chap 15 xác nhận có đủ marker); `run_transcribe` GIỮ nguyên (cloud GPU).
2. Mặc định KHÔNG mood overlay — bỏ bước "đề xuất mood + chờ" trong workflow doc (code đã default off).
3. (#5) Ưu tiên WAV, fallback MP3 khi auto-detect voice.
4. (#6) Sub vàng CHỈ audio-story — field `enhance.subtitle_color` (default trắng), thread → `caption_filter`.
5. (#7) Audio AAC 256k (3 chỗ), giữ loudnorm −14 LUFS.

**Acceptance:** `.venv/bin/python -m pytest -q` ≥66 passing; ffprobe xác nhận aac 256k; sub audio-story hiển thị vàng viền đen; job.yaml cũ vẫn validate (backward-compat).

**Non-goals:** SFX, music-schedule, đổi loudnorm target, đổi màu sub cho job không phải audio-story.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Code changes (subtitle-color + AAC 256k)](./phase-01-code-changes-subtitle-color-aac-256k.md) | Completed |
| 2 | [Workflow & skill updates (SRT/mood/WAV)](./phase-02-workflow-skill-updates-srt-mood-wav.md) | Completed |
| 3 | [Verify (pytest + ffprobe)](./phase-03-verify-pytest-ffprobe.md) | Completed |

## Dependencies

<!-- Cross-plan dependencies -->
