---
phase: 1
title: Music-schedule staging (audio.music_schedule)
status: completed
effort: ''
---

# Phase 1: Music-schedule staging (audio.music_schedule)

## Overview

Cho phép đặt từng track nhạc vào đúng khoảng thời gian theo mood truyện. Thêm `audio.music_schedule` (optional); khi có, `_stage_music` dựng bed theo lịch (mỗi cue = 1 track loop/trim đầy cửa sổ của nó, crossfade ở ranh giới) thay cho concat-loop. Bed vẫn là 1 FLAC phủ target_duration → **render graph không đổi**.

## Requirements

- Functional: `audio.music_schedule: [{track, start, end, gain_db?}]` (track = tên file trong Music/ hoặc index 1-based; start/end giây, narration-aligned). Tool render bed sao cho mỗi khoảng phát đúng track. Vắng field → concat-loop cũ y hệt.
- Non-functional: backward-compat (field optional, default None); không đổi output khi không set; CTA offset áp đúng.

## Architecture

`prepare_scheduled_music(cues, target_duration, workspace)` (mới, trong `music_loop.py`) — mirror `prepare_seamless_music`: cho mỗi cue dựng segment `track` (loop bằng `-stream_loop`/`aloop` hoặc lặp acrossfade cho tới `end-start`, rồi atrim), nối các segment bằng `acrossfade` (tái dùng chuỗi normalize+acrossfade sẵn có), atrim tổng về target_duration, FLAC out. Trả path — `_stage_music` dùng thay raw music.

Offset CTA: cue narration-aligned. `_stage_music` đã biết `cta.intro_seconds`. Shift toàn bộ cue `+intro_seconds`; khoảng `[0, intro_seconds]` (vùng intro CTA) lấp bằng track của cue đầu. Cuối cùng bed vẫn = target_duration (đã gồm CTA) như hiện tại.

Track resolve: tái dùng `_resolve_music_tracks` (natural-sort) → map `track` (index i↔track i, hoặc match tên) sang path. Khối prompt i ↔ track i do LLM căn ở Phase 3 (doc), tool chỉ nhận cue.

## Related Code Files

- Modify: `src/videotool/core/job_spec.py` — `AudioSpec`: thêm `music_schedule: list[MusicCueSpec] | None = None`; class `MusicCueSpec` (track: str|int, start/end: float ge 0, gain_db: float|None). Validator: end>start, cues sorted & non-overlapping.
- Modify: `src/videotool/render/music_loop.py` — thêm `prepare_scheduled_music(...)` + helper build-segment-per-cue.
- Modify: `src/videotool/core/services.py` — `_stage_music`: nếu `job.audio.music_schedule` → resolve track paths + shift CTA + gọi `prepare_scheduled_music`; else nhánh cũ.
- (Không sửa) `render/commands.py`, `segmented.py`, `audio_graph.py` — bed vẫn là 1 input.

## Implementation Steps

1. **Schema**: `MusicCueSpec(track: str|int, start: float ge0, end: float gt start, gain_db: float|None=None)`; `AudioSpec.music_schedule: list[MusicCueSpec] | None = None`. Model-validator: sort theo start, đảm bảo không chồng lấn (`cue[i].start >= cue[i-1].end - eps`), track hợp lệ (index 1..N hoặc tên tồn tại — validate ở render-time khi biết Music/).
2. **music_loop.prepare_scheduled_music(cues_with_paths, target_duration, workspace, crossfade)**: mỗi cue → dựng đoạn `track` phủ `end-start` (nếu track ngắn hơn: lặp qua `_build_sequence` 1-track; nếu dài hơn: atrim). Nối các đoạn qua acrossfade (tái dùng logic `_build_loop_command`). atrim tổng = target_duration, afade tail. FLAC out. Áp `gain_db` per-cue nếu có (volume filter trên đoạn).
3. **services._stage_music**: nếu có schedule → resolve mỗi cue.track → path (index/tên qua `_resolve_music_tracks`); shift start/end `+= cta.intro_seconds`; chèn cue-0 phủ `[0, first.start]`; gọi `prepare_scheduled_music(..., target_duration)`. Không schedule → nhánh cũ.
4. Cover mép: nếu cue cuối `end < target_duration` → kéo dài cue cuối tới target (music không im ở đuôi).

## Success Criteria

- [ ] job.yaml không có `music_schedule` → bed + command byte-tương đương hiện tại (test).
- [ ] Có schedule 3 cue → bed FLAC dài = target_duration; mỗi khoảng phát đúng track (probe/kiểm command).
- [ ] Cue chồng lấn / end<=start → ValidationError rõ ràng.
- [ ] gain_db per-cue áp đúng (volume trong filter).
- [ ] CTA intro: bed vùng đầu = track cue-0; tổng phủ đủ target (gồm CTA).

## Risk Assessment

- **acrossfade nhiều đoạn dài** → command dài; tái dùng MAX_PLAYS cap + báo lỗi actionable.
- **Track ngắn hơn cửa sổ** → loop trong cue; đảm bảo không seam (acrossfade nội bộ) — tái dùng `_build_sequence`.
- **Offset CTA sai** → nhạc lệch story; test riêng ca có/không CTA. Đây là rủi ro chính, verify kỹ Phase 4.
- **Regression concat-loop**: nhánh cũ giữ nguyên; test no-schedule byte-đồng nhất.
