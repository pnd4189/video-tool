---
phase: 1
title: Code changes (subtitle-color + AAC 256k)
status: completed
effort: ''
---

# Phase 1: Code changes (subtitle-color + AAC 256k)

## Overview

Ba thay đổi code: (a) field `enhance.subtitle_color` + thread qua Timeline → `caption_filter` (default trắng, giữ hành vi cũ); (b) AAC 192k→256k ở 3 chỗ; (c) **bộ sinh chapters từ SRT** (`chapters-from-srt`) thay cho phần chapters mà whisper cũ tạo — bắt buộc, nếu không audio-story mất chapter YouTube khi bỏ transcribe. #2/#5 là workflow-doc thuần (Phase 2).

**Xác nhận từ SRT thật Chap 15** (`Binh_Thien_Sach_0141_0150_vi_qa.srt`): có đủ 10 marker `Chương NNN:` nằm ngay trong cue có timecode → sinh chapters deterministic không cần whisper. Quirk: vài marker dính dấu `"` đầu dòng (`" Chương 143:`, `" Chương 149:`) → regex phải strip ký tự đầu không phải chữ. Marker cũng là dòng đầu của cue, title có thể trải 2 dòng text.

## Requirements

- Functional: job.yaml có thể set `enhance.subtitle_color: yellow` → sub burn vàng viền đen. Không set → trắng (byte-tương đương output hiện tại). Audio render ra AAC 256k.
- Non-functional: backward-compat (job.yaml cũ không có field vẫn validate — `extra=forbid` OK vì field mới có default). Không đổi số test đang pass (trừ test mới thêm).

## Architecture

Luồng màu sub: `EnhanceSpec.subtitle_color` (job_spec) → `compile_timeline` set `Timeline.enhance_subtitle_color` → `caption_filter` (overlay_graph) map tên màu → ASS `PrimaryColour`/`OutlineColour`, chèn vào `force_style`.

ASS color = `&HAABBGGRR` (alpha-blue-green-red, hex, AA=00 opaque). Bảng map:
- `white` (default) → KHÔNG thêm PrimaryColour (giữ nguyên chuỗi style hiện tại → output cũ không đổi).
- `yellow` → `PrimaryColour=&H0000FFFF` (R=FF,G=FF,B=00) + `OutlineColour=&H00000000` (đen).

Chỉ thêm khoá màu khi != white → job cũ/không audio-story giữ style y hệt hiện tại (an toàn regression).

## Related Code Files

- Modify: `src/videotool/core/job_spec.py` — thêm field vào `EnhanceSpec`.
- Modify: `src/videotool/core/timeline.py` — thêm field Timeline + set trong `compile_timeline`.
- Modify: `src/videotool/render/overlay_graph.py` — `caption_filter` đọc màu, map ASS, chèn force_style.
- Modify: `src/videotool/render/commands.py` (dòng 79, 139) — 192k→256k.
- Modify: `src/videotool/render/segmented.py` (dòng 120) — 192k→256k.
- Modify: `src/videotool/core/chapter_timing.py` — thêm `chapters_from_srt(srt_text) -> list[tuple[float, str]]`; sửa `CHAPTER_RE` để tolerant dấu đầu dòng (`^\s*["']?\s*Chương\s+\d+`).
- Modify: `src/videotool/core/services.py` — thêm `run_chapters_from_srt(job_path)` (đọc `outputs/captions.srt` → ghi `outputs/chapters.json`; skip nếu <2 chương, giống transcribe).
- Modify: `src/videotool/cli/commands.py` + `src/videotool/cli/main.py` — thêm command `chapters-from-srt "$JOB"` (mirror `transcribe`).

## Implementation Steps

1. **job_spec.py `EnhanceSpec`** (sau `atmosphere`, ~dòng 160): thêm
   ```python
   # Burned-subtitle fill colour. Default white keeps existing output byte-identical;
   # audio-story flow seeds "yellow" for readability. Only applied when subtitles burn.
   subtitle_color: Literal["white", "yellow"] = "white"
   ```
   (`Literal` đã import ở đầu file.)
2. **timeline.py**: thêm field dataclass (cạnh `enhance_color_grade`, ~dòng 61):
   `enhance_subtitle_color: str = "white"`.
   Trong `compile_timeline` return (cạnh `enhance_color_grade=...`): `enhance_subtitle_color=job.enhance.subtitle_color,`.
3. **overlay_graph.py `caption_filter`** (~dòng 136): sau khi build `style`, thêm phần màu trước khi return:
   ```python
   color = getattr(timeline, "enhance_subtitle_color", "white")
   if color == "yellow":
       style += ",PrimaryColour=&H0000FFFF,OutlineColour=&H00000000"
   ```
   Giữ `Outline=3,Shadow=1` như cũ. (Dùng string concat để `white` không đổi chuỗi.)
4. **commands.py:79** và **commands.py:139**: `"-b:a", "192k"` → `"-b:a", "256k"`.
5. **segmented.py:120**: `"-b:a", "192k"` → `"-b:a", "256k"`.
6. **chapter_timing.py**: sửa `CHAPTER_RE` → `re.compile(r"^\s*[\"'“]?\s*Chương\s+\d+", re.IGNORECASE)`. Thêm `chapters_from_srt(srt_text)`: parse cue (index / `hh:mm:ss,mmm --> ...` / text), với cue có text match CHAPTER_RE → `(start_seconds, title)`, title = join dòng text của cue, strip dấu đầu. Trả list theo thứ tự thời gian.
7. **services.py**: `run_chapters_from_srt(job_path)` — đọc `outputs/captions.srt`, gọi `chapters_from_srt`, ghi `outputs/chapters.json` (`[{start,title}]`, `ensure_ascii=False`). Skip ghi nếu <2 chương. Không đụng `run_transcribe`.
8. **cli**: thêm command `chapters-from-srt` gọi `run_chapters_from_srt` (song song `transcribe`, không thay thế nó).

## Success Criteria

- [ ] `enhance.subtitle_color` validate được (yellow/white); giá trị khác → ValidationError.
- [ ] Không set field → `caption_filter` trả chuỗi force_style y hệt hiện tại (không có PrimaryColour).
- [ ] `subtitle_color: yellow` → force_style chứa `PrimaryColour=&H0000FFFF` + `OutlineColour=&H00000000`.
- [ ] 3 chỗ audio đều `256k`; không còn `192k` trong `src/` (grep sạch).
- [ ] loudnorm giữ `I=-14` (không đụng `audio_graph.py`).
- [ ] `chapters_from_srt` parse đúng SRT Chap 15 → 10 chương, đúng title (kể cả `Chương 143/149` dính dấu `"`), start-seconds khớp cue.
- [ ] `videotool chapters-from-srt "$JOB"` ghi `outputs/chapters.json`; `run_transcribe` không đổi.

## Risk Assessment

- **Regression style sub trắng**: giảm thiểu bằng concat có điều kiện (white không thêm gì) + test so khớp chuỗi cũ.
- **Backward-compat schema**: field có default → job.yaml cũ pass. Thêm test load job cũ.
- **Lệch bitrate inline vs segmented**: sửa đủ cả 3 dòng; Phase 3 grep xác nhận.
