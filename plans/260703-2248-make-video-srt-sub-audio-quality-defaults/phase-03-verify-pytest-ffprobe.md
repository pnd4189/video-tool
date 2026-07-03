---
phase: 3
title: Verify (pytest + ffprobe)
status: completed
effort: ''
---

# Phase 3: Verify (pytest + ffprobe)

## Overview

Kiểm chứng Phase 1+2: unit tests cho subtitle-color + bitrate + backward-compat schema, chạy full suite (≥66 passing), và ffprobe xác nhận aac 256k trên 1 render thật (hoặc dry-run command chứa 256k).

## Requirements

- Functional: test bao phủ 3 điểm code mới; full suite xanh.
- Non-functional: verify thật (render/ffprobe), không chỉ đọc code.

## Related Code Files

- Create/Modify: test tương ứng dưới `tests/` (theo cấu trúc test hiện có — grep `caption_filter`, `192k`, `build_audio` để tìm test gần nhất).

## Implementation Steps

1. **Test subtitle color** (unit, gọi `caption_filter` với timeline giả):
   - default (`white`) → chuỗi force_style KHÔNG chứa `PrimaryColour` (khớp baseline hiện tại).
   - `yellow` → chứa `PrimaryColour=&H0000FFFF` + `OutlineColour=&H00000000`.
2. **Test bitrate**: build command (inline `commands.py`, segmented `segmented.py`) → assert `"256k"` có mặt, `"192k"` vắng.
3. **Test backward-compat**: load 1 job.yaml KHÔNG có `subtitle_color` → validate OK, `enhance.subtitle_color == "white"`.
3b. **Test `chapters_from_srt`**: fixture SRT nhỏ mô phỏng Chap 15 (gồm 1 marker sạch + 1 marker dính dấu `"` + title trải 2 dòng) → assert đúng số chương, title strip dấu đầu, start-seconds = start của cue chứa marker. Edge: SRT <2 marker → không ghi chapters.json.
4. **Chạy suite**: `.venv/bin/python -m pytest -q` → ≥66 passing.
5. **ffprobe thật**: nếu có job mẫu nhỏ, render `youtube-16x9` rồi
   `ffprobe -v error -show_entries stream=codec_name,bit_rate -select_streams a -of csv=p=0 out.mp4` → aac; hoặc tối thiểu dry-run render in command chứa `256k`. Với sub vàng: render 1 clip audio-story ngắn, mở khung hình xác nhận chữ vàng viền đen (hoặc kiểm filtergraph chứa PrimaryColour).
6. Grep chốt: `grep -rn '192k' src/` → rỗng.

## Success Criteria

- [ ] Test subtitle-color (white + yellow) pass.
- [ ] Test bitrate 256k (inline + segmented) pass.
- [ ] Test backward-compat schema pass.
- [ ] Test `chapters_from_srt` pass (marker sạch + dính dấu + title 2 dòng + edge <2 chương).
- [ ] `pytest -q` ≥66 passing, 0 fail.
- [ ] ffprobe/dry-run xác nhận aac + 256k; sub audio-story vàng.
- [ ] `grep -rn '192k' src/` rỗng.

## Risk Assessment

- **Test baseline sub trắng đổi**: nếu có snapshot test chuỗi force_style, cập nhật kỳ vọng CHỈ khi white thực sự không đổi (nếu đổi là bug Phase 1).
- **Không có sample render nhanh**: fallback dry-run command-string assert thay vì render đầy đủ.
