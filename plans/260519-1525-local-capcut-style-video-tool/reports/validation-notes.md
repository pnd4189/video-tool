---
title: "Validation Notes"
status: final
created: "2026-05-19"
---

# Validation Notes

## User Requirements Captured

- Outputs: both YouTube 16:9 and Shorts/TikTok 9:16.
- Inputs: voice/audio, folder of images/videos, background music.
- Background music: must match voice duration.
- GUI: lightweight selector/queue is enough; CLI/script workflow is primary.
- AI: optimize for local machine; TTS integration later.
- Minimum upload package: advise YouTube-ready standard, not only MP4.
- Hardware: Ryzen 5 7640HS/Radeon 760M, current visible RAM about 16GB class, 32GB after upgrade.

## Validation Questions For User

These can be answered during implementation:

1. Subtitle style: burn captions into video by default, or provide `.srt` only unless requested?
2. Batch policy: render both 16:9 and 9:16 every job by default, or selectable presets?
3. TTS integration: CLI hook path/contract for the existing TTS tool.

## Verification Results

- Tier: Full, because plan has 8 phases.
- Codebase claims checked: repo/file existence, plans folder, FFmpeg availability, encoder availability, hardware summary.
- Verified: repo empty except git and newly created plan files; FFmpeg exists; VAAPI encoders listed; Python 3.12 and Node available.
- Failed: none.
- Unverified: default subtitle burn-in behavior, TTS hook contract; intentionally left as open decisions.

## Whole-Plan Consistency Sweep

- Files reread: `plan.md`, all 8 phase files, research summary, scout report, red-team review.
- Decision deltas checked: V1 scope, CLI-first architecture, CPU default encoder, optional VAAPI, `faster-whisper` default, local web GUI, manual asset import, asset licensing.
- Reconciled stale references: duplicate implementation-step headings removed.
- Unresolved contradictions: 0.
