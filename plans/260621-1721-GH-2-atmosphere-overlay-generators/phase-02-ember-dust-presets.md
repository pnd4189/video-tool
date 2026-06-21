---
phase: 2
title: Ember + dust presets
status: completed
priority: P2
dependencies:
  - 1
effort: ''
---

# Phase 2: Ember + dust presets

## Overview
Thêm 2 preset point-sprite vào engine phase 1: tàn lửa bùa符 (tia cam bay lên + tắt dần) và bụi lơ lửng (đốm trắng-xám rất chậm, mờ, dày). Chủ yếu là bộ tham số + một biến thể lifecycle cho ember; KHÔNG viết engine mới.

## Requirements
- Functional: `gen_overlay.py --preset ember` → `ember-gen-01.mp4`; `--preset dust` → `dust-gen-01.mp4`.
- Non-functional: cùng spec phase 1 (nền đen, seamless, 0 dep); chạy local < 2 phút/clip.

## Architecture
- **Dust = thuần tham số** trên engine phase 1: count dày (~150-220), màu trắng-xám nhạt, `drift_amp_px` rất nhỏ (gần như đứng yên — "suspended unnaturally still"), brightness thấp, nháy rất nhẹ/không nháy.
- **Ember cần thêm lifecycle** (spawn→bay lên→tắt): mỗi particle có `phase ∈ [0,1)` tiến `+1/N` mỗi frame, **wrap** → frame N trở về frame0 (seamless). Vị trí y giảm dần theo phase (bay lên), alpha = đường cong fade theo phase (sáng giữa đời, tắt cuối), x lắc nhẹ bằng sin. Màu cam-đỏ (#ff7a2a→#ff3b2a), dày ở đáy, count vừa.
- Thêm tham số tùy chọn vào engine: `lifecycle: bool`, `rise_px`, `fade_curve`. Khi `lifecycle=False` (đom đóm/bụi) → giữ nguyên đường phase-tuần-hoàn vị trí của phase 1.
- Giữ DRY: 1 hàm splat + 1 vòng render; lifecycle chỉ đổi cách tính pos/alpha theo `t`.

## Related Code Files
- Modify: `scripts/gen_overlay.py` (thêm 2 entry vào `PRESETS` + nhánh `lifecycle` trong vòng render)
- Modify: `tests/test_overlay_gen.py` (parametrize seam + black-bg cho cả `ember`, `dust`)

## Implementation Steps
1. Thêm `PRESETS["dust"]` (tham số như trên); chạy sinh `dust-gen-01.mp4`; verify ffprobe.
2. Thêm cờ `lifecycle` + `rise_px`/`fade_curve` vào engine; nhánh tính pos/alpha khi lifecycle bật. Đảm bảo phase wrap `+1/N` để seamless.
3. Thêm `PRESETS["ember"]`; sinh `ember-gen-01.mp4`; verify ffprobe.
4. Verify screen-blend trên frame thật cho cả 2 (ember sáng cam nổi, dust chìm mờ — chỉnh brightness/count nếu wash hoặc quá mờ không thấy).
5. Parametrize test seam + black-bg cho `ember` và `dust` (ember lifecycle vẫn phải seam-pass nhờ phase wrap).

## Success Criteria
- [ ] `ember-gen-01.mp4` + `dust-gen-01.mp4` sinh ra đúng spec (1920×1080 h264 yuv420p ~18s), < 2 phút/clip.
- [ ] Cả 2 seam-pass + black-bg-pass trong test.
- [ ] Screen-blend frame thật: ember = tia cam bay lên rõ; dust = bụi chìm tinh tế, không wash.
- [ ] Không viết engine mới — chỉ tham số + nhánh lifecycle (DRY).

## Risk Assessment
- **Ember seam lộ** nếu fade không khép vòng (alpha ở phase→1 khác phase→0) → đảm bảo `fade_curve(0)==fade_curve(1)==0` và phase wrap chuẩn.
- **Dust quá mờ thành vô hình** sau screen-blend → cân brightness vs "chìm tinh tế"; verify frame thật.
- **Ember quá dày → washout cam** → giảm count/brightness.
