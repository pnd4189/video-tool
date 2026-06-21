---
title: Atmosphere overlay generators (đom đóm + tàn lửa + bụi + linh khí)
description: ''
status: in-progress
priority: P2
branch: feat/parallax-2-5d
tags: []
blockedBy: []
blocks: []
created: '2026-06-21T10:41:24.199Z'
createdBy: 'ck:plan'
source: skill
---

# Atmosphere overlay generators (đom đóm + tàn lửa + bụi + linh khí)

## Overview

Mở rộng thư viện atmosphere overlay (`~/.local/share/videotool/overlays/`) bằng 4 hiệu ứng bám bối cảnh truyện siêu nhiên/linh dị: **đom đóm, tàn lửa bùa符, bụi lơ lửng, linh khí**. Generator là **công cụ tạo asset OFFLINE**, KHÔNG nối vào render pipeline — chạy 1 lần, xuất mp4 (1920×1080, H264 yuv420p, nền đen tuyệt đối, loop seamless ~15-20s), bỏ vào library; pipeline tiêu thụ qua `inputs.particle_overlay` y như mọi clip CC0 khác.

Tech (đã chốt ở brainstorm): 3 hiệu ứng point-sprite (đom đóm/tàn lửa/bụi) = generator numpy→ffmpeg in-repo tái dùng pattern `src/videotool/render/parallax.py` (0 dep mới); linh khí (flow-field) = GLSL shader render trên Colab GPU (chỗ duy nhất GPU đáng giá). Brainstorm: `plans/reports/brainstorm-atmosphere-overlay-generators-260621-1721-GH-2-numpy-pointsprite-colab-glsl-report.md`.

**Hợp đồng kỹ thuật (verified):** `particle_input_args` (overlay_graph.py:145) chỉ `-stream_loop -1 -i <mp4>`; atmosphere blend scale+crop về preset + `blend=all_mode=screen` trong `gbrp` (overlay_graph.py:63-76) → nền đen biến mất, chỉ điểm sáng hiện. Seamless loop bắt buộc vì pipeline loop vô hạn (~250 vòng/49 phút) → frame0 phải == frameN. Pattern parallax.py đã làm đúng kiểu này: `ph = 2π·i/n`.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Point-sprite engine + fireflies preset](./phase-01-point-sprite-engine-fireflies-preset.md) | Completed |
| 2 | [Ember + dust presets](./phase-02-ember-dust-presets.md) | Completed |
| 3 | [Qi-wisps GLSL shader on Colab](./phase-03-qi-wisps-glsl-shader-on-colab.md) | In Progress |
| 4 | [Docs mood-map + memory](./phase-04-docs-mood-map-memory.md) | Completed |

Build order: P1 (engine + 1 preset, kiểm seam + screen-blend trên frame thật) → P2 (2 preset point-sprite còn lại) → P3 (linh khí, tech khác, tách riêng — có thể ship sau 3 cái numpy) → P4 (doc/memory sau khi đủ 4 kind).

## Acceptance Criteria

- [ ] 4 mp4 trong `~/.local/share/videotool/overlays/`: `fireflies-gen-01`, `ember-gen-01`, `dust-gen-01`, `qi-gen-01`.
- [ ] Mỗi clip: nền đen tuyệt đối, loop seamless (không thấy seam khi `-stream_loop`), screen-blend sạch (không halo/wash), hợp genre.
- [ ] 3 generator numpy: 0 dep mới, chạy local < 2 phút/clip.
- [ ] Dùng được trong 1 render ĐẠO SĨ thật — nền chìm tinh tế, không cướp chú ý audio.
- [ ] AGENTS.md mood-map + memory `overlay-fx-library` cập nhật.

## Dependencies

Không phụ thuộc plan khác. Tiêu thụ overlay (`enhance.atmosphere`/`inputs.particle_overlay`) đã ship ở `260615-1820-full-tier-effects-and-moods` — plan này chỉ **sinh input** cho path đó, không sửa pipeline. Không blocking.
