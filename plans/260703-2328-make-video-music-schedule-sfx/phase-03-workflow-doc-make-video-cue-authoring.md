---
phase: 3
title: Workflow doc (make-video cue authoring)
status: completed
effort: ''
---

# Phase 3: Workflow doc (make-video cue authoring)

## Overview

AGENTS.md: hướng dẫn agent lúc `/make-video` tự sinh `audio.music_schedule` + `enhance.sfx.cues` (LLM là bộ phân loại), và chèn bước `sfx` vào pipeline. Không đổi code.

## Requirements

- Functional: agent biết cách (a) map track↔khoảng chương theo mood, (b) scan+pin SFX, (c) thứ tự pipeline render→sfx→package.
- Non-functional: giữ AGENTS.md gọn; chi tiết dài dời `docs/` nếu cần.

## Related Code Files

- Modify: `AGENTS.md` — mục "Audio-story channel default" + "Standard pipeline" + "Confirmed project decisions".
- (Tham chiếu) memory `sfx-insertion-workflow`, `sfx-library-location`, `overlay-fx-library`.

## Implementation Steps

1. **Music-schedule authoring** (mục audio-story): đọc `*_vi_qa.txt` + `*_music_prompts.txt` (N khối mood theo thứ tự, **khối i ↔ track i** natural-sort trong `Music/`) + mốc giây từ marker "Chương N:" trong `outputs/captions.srt`. Gán mỗi track vào khoảng chương hợp mood (calm/tả cảnh→track nhẹ; hành động/cao trào→track dồn dập). Ghi `audio.music_schedule` (narration-aligned, cover hết voice). Track không hợp → bỏ hoặc lấp khoảng.
2. **SFX authoring** (auto-burn, mật độ 12–15 cue/45ph, scale theo độ dài):
   - Scan `outputs/captions.srt` keyword hành động (chém/đao/kiếm/tên/nỏ/ngựa/nổ/va chạm…); **lọc đồng âm ẩn dụ** (grep ngữ cảnh, bỏ `chấn động lòng`, `đâm ra=jut`…).
   - **Pin bằng nội suy ký tự** trong cue (KHÔNG dùng segment-start, KHÔNG re-transcribe): tìm vị trí cụm từ trong text cue → `start + frac*(end-start)`.
   - Palette: LLM tự nhận theo thể loại (kiếm hiệp→`binh-thien`, ma hài→`dao-si`); chọn file `~/.local/share/videotool/sfx/<pack>/` khớp beat; normalize gain per-cue (point-SFX −8..−15 dB dưới voice).
   - Cluster ở cao trào, ~0 ở exposition; ≥30–60s giữa cụm; ≤3 SFX/10s; tránh 30s đầu / 25s cuối (vùng CTA). Ghi `enhance.sfx.cues` (narration-aligned). **Auto, không montage.**
3. **Pipeline order** (Standard pipeline + audio-story): `render` → `$VT sfx "$JOB"` → `package`. Ghi rõ SFX chạy sau render (remux `-c:v copy`), music-schedule tự động khi có `audio.music_schedule`.
4. **Confirmed decisions**: cập nhật dòng 2026-07-03 Plan 2 từ "later" → "shipped": music-schedule per-chương + SFX auto-burn 12–15/45ph post-process; beds vẫn để sau.

## Success Criteria

- [ ] Doc mô tả cách map track↔chương theo mood + khối i↔track i.
- [ ] Doc mô tả scan+lọc đồng âm + pin nội suy + palette + density + vùng tránh CTA.
- [ ] Pipeline ghi rõ render→sfx→package.
- [ ] Confirmed decisions cập nhật (beds vẫn để sau).

## Risk Assessment

- **Agent pin sai** → phản cảm: nhấn mạnh nội suy ký tự + lọc đồng âm (bài học T12) trong doc.
- **AGENTS.md phình**: nếu quá dài, tách chi tiết SFX/music authoring sang `docs/`, AGENTS.md chỉ trỏ.
