---
phase: 2
title: Workflow & skill updates (SRT/mood/WAV)
status: completed
effort: ''
---

# Phase 2: Workflow & skill updates (SRT/mood/WAV)

## Overview

Cập nhật doc workflow (CLAUDE.md — canonical, symlink AGENTS.md/GEMINI.md) để `/make-video` mặc định: (#1) dùng SRT user cấp thay vì `transcribe`; (#2) KHÔNG đề xuất/chờ mood; (#5) ưu tiên WAV; (#6) seed `subtitle_color: yellow` cho audio-story. Đây là thay đổi hướng dẫn agent + 1 dòng seed job.yaml, KHÔNG đổi code render (đã xong ở Phase 1).

## Requirements

- Functional: agent chạy `/make-video` theo doc mới → không gọi `transcribe` ở flow mặc định; cp SRT user → `outputs/captions.srt`; chapters từ marker "Chương NNN:"/SRT hoặc `project.chapters`; chọn voice ưu tiên `.wav`; seed `enhance.subtitle_color: yellow` cho job audio-story.
- Non-functional: `run_transcribe` CLI vẫn còn (cloud GPU path giữ nguyên); không xoá pattern transcribe khỏi Tech notes, chỉ hạ khỏi "flow mặc định".

## Architecture

CLAUDE.md là nguồn duy nhất (symlinked). Sửa các mục: "Standard pipeline", "Audio-story channel default", "Confirmed project decisions", "Known pitfalls". `~/.claude/skills/make-video/SKILL.md` chỉ trỏ về AGENTS.md → không cần sửa (xác nhận trong bước 1).

## Related Code Files

- Modify: `CLAUDE.md` (== `AGENTS.md`, `GEMINI.md` symlink) — mục pipeline + decisions.
- Verify only: `~/.claude/skills/make-video/SKILL.md` — chỉ đọc, sửa nếu nó nhúng bước transcribe/mood cứng.

## Implementation Steps

1. **Đọc trước khi sửa**: `CLAUDE.md` mục "Audio-story channel default", "Scan & advise FX / mood", "Standard pipeline", "Confirmed project decisions"; và `~/.claude/skills/make-video/SKILL.md`.
2. **#2 mood**: trong mục "Scan & advise FX / mood" — đổi thành: mặc định KHÔNG bật mood/atmosphere, KHÔNG đề xuất-chờ; chỉ bật khi user yêu cầu rõ. Gỡ câu "print ONE proposal line and WAIT".
3. **#1 whisper→SRT**: mục "Audio-story channel default" + "Standard pipeline" — thay bước `transcribe "$JOB" --model ...` bằng 2 bước: (a) `cp "<user_srt>" "$JOB_DIR/outputs/captions.srt"`; (b) `$VT chapters-from-srt "$JOB"` (sinh `outputs/chapters.json` từ marker "Chương NNN:"; <2 chương → bỏ qua, như hiện tại). SRT thật (Chap 15) xác nhận có đủ marker. Ghi chú: `transcribe` chỉ dùng khi user KHÔNG cấp SRT / cloud GPU (giữ nguyên trong Tech notes).
4. **#5 WAV**: mục asset-detect / init-job — thêm: auto-detect voice ưu tiên `.wav` > `.m4a` > `.mp3`; note "chỉ có mp3 thì dùng mp3, không fail".
5. **#6 sub vàng**: mục "Audio-story channel default" — seed `enhance.subtitle_color: yellow` vào job.yaml cho audio-story; note "chỉ audio-story, job light khác giữ trắng".
6. **Confirmed project decisions**: thêm 4 dòng quyết định (ngày 2026-07-03): SRT-provided default, no-mood default, WAV-first, yellow audio-story subs + AAC 256k. Cập nhật mục caption/subtitles cũ nếu mâu thuẫn.
7. **Known pitfalls**: cập nhật pitfall #3 (captions.mode) cho nhất quán flow SRT-provided.
8. Giữ CLAUDE.md ≤ ~150 dòng (rule cuối file); nếu quá, gộp/rút gọn, chi tiết dời `docs/`.

## Success Criteria

- [ ] Doc "Standard pipeline" + "Audio-story channel default" KHÔNG còn `transcribe` ở bước mặc định; có bước cp SRT + `chapters-from-srt`.
- [ ] Không còn câu "propose mood + WAIT"; mặc định no-mood ghi rõ.
- [ ] Có hướng dẫn ưu tiên WAV + fallback mp3.
- [ ] Có seed `enhance.subtitle_color: yellow` cho audio-story.
- [ ] "Confirmed project decisions" ghi 5 quyết định mới (2026-07-03).
- [ ] `run_transcribe`/Tech notes cloud GPU vẫn còn.
- [ ] CLAUDE.md ≤ ~150 dòng.

## Risk Assessment

- **Mâu thuẫn doc cũ** (decision "audio-story subtitles ON via transcribe"): phải sửa cả chỗ cũ, không để 2 câu trái nhau → whole-plan consistency sweep.
- **Skill nhúng bước cứng**: nếu SKILL.md có transcribe/mood cứng thì sửa; nếu chỉ trỏ AGENTS.md thì bỏ qua.
- **Chapters khi SRT thiếu marker**: doc phải nêu fallback `project.chapters` / bỏ qua chapters (đã có `_load_chapters`).
