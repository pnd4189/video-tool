---
phase: 3
title: Qi-wisps GLSL shader on Colab
status: in-progress
priority: P2
dependencies:
  - 1
effort: ''
---

# Phase 3: Qi-wisps GLSL shader on Colab

## Overview
Sinh overlay linh khí (qi wisps) — tua/sợi sáng mềm cuộn theo flow-field — bằng GLSL fragment shader render trên Colab GPU. Đây là primitive thứ 2 (flow-field, KHÔNG phải point-sprite), là hiệu ứng duy nhất GPU thắng rõ. Tách riêng: có thể ship sau 3 preset numpy.

## Requirements
- Functional: notebook/script Colab render `qi-gen-01.mp4` (1920×1080, h264 yuv420p, nền đen, loop seamless ~18s). Download thủ công → đặt vào `~/.local/share/videotool/overlays/qi-gen-01.mp4`.
- Non-functional: chạm GPU NVIDIA thật trên Colab (không software-render); seamless loop; nền đen tuyệt đối.

## Architecture
- **Tech:** GLSL fragment shader curl-noise flow-field, render headless qua **moderngl + EGL** (chạm GPU không cần display) HOẶC torch-CUDA frame-gen — chốt khi prototype. KHÔNG Three.js/Remotion (headless WebGL hay rơi SwiftShader/CPU trên Colab — xem brainstorm report).
- **Vị trí:** `Colab/qi_wisps_overlay_colab.py` (theo pattern `/Colab` hiện có: `v4_depthflow_clips_colab.py` — render trên Colab, download thủ công, đặt cạnh asset). Nhất quán quyết định "GPU → Colab".
- **Shader:** curl-noise (gradient của Perlin/simplex) tạo flow-field; sample mật độ sáng theo field; màu lam-lục linh khí mờ (#7fd6c0 nhạt). Dùng `shader` skill để soạn/kiểm GLSL.
- **Seamless loop:** thời gian `t = 2π·frame/N`; lấy noise tuần hoàn theo `t` (sample noise trên 1 vòng tròn trong chiều thời gian: `noise(x, y, cos t, sin t)`) → frame0 == frameN.
- **Output:** shader render ra frames → ffmpeg (trong notebook) → mp4 yuv420p nền đen.
- **Fallback (nếu Colab EGL/GPU quá đau):** numpy curl-noise xấp xỉ local (chậm hơn, xấu hơn chút nhưng đủ cho nền chìm) — ghi rõ là fallback, không phải mặc định.

## Related Code Files
- Create: `Colab/qi_wisps_overlay_colab.py` (shader GLSL + moderngl/EGL render + ffmpeg encode + cell hướng dẫn download)
- Reference: `Colab/v4_depthflow_clips_colab.py` (pattern Colab + download thủ công), brainstorm report (lý do không Three.js/Remotion)
- Output đích (thủ công): `~/.local/share/videotool/overlays/qi-gen-01.mp4`

## Implementation Steps
1. Soạn GLSL fragment shader curl-noise flow-field (dùng `shader` skill); tham số màu/mật độ/tốc độ cuộn; thời gian tuần hoàn cho seamless.
2. Viết `Colab/qi_wisps_overlay_colab.py`: setup moderngl+EGL (hoặc torch-CUDA), render N frame 1920×1080 → pipe ffmpeg → `qi-gen-01.mp4`. Kiểm GPU thật được dùng (`nvidia-smi` hiện process / EGL device là GPU, không llvmpipe).
3. Chạy trên Colab, verify ffprobe + xem loop seam + nền đen.
4. Download → đặt `~/.local/share/videotool/overlays/qi-gen-01.mp4`; verify screen-blend trên frame thật (tua sáng mềm hiện, nền không wash).
5. Nếu Colab GPU/EGL không khả thi trong thời gian hợp lý → bật fallback numpy curl-noise local, ghi chú trong notebook + memory.

## Success Criteria
- [ ] `qi-gen-01.mp4` (1920×1080 h264 yuv420p ~18s, nền đen) có trong library.
- [ ] Render thật sự trên GPU Colab (xác nhận không software/llvmpipe) — hoặc fallback numpy nếu được ghi chú rõ.
- [ ] Loop seamless + screen-blend sạch trên frame thật (tua linh khí mờ ảo, không wash).
- [ ] KHÔNG dùng Three.js/Remotion.

## Risk Assessment
- **Headless GPU GL trên Colab khó setup (EGL/driver)** → có fallback numpy curl-noise; timebox trước khi đổ công.
- **Seam lộ ở flow-field** nếu noise không tuần hoàn theo `t` → bắt buộc sample noise trên vòng tròn thời gian.
- **Quá mờ/vô hình hoặc quá đặc** sau screen-blend → tinh chỉnh mật độ/brightness; verify frame thật.
- **Phụ thuộc thao tác thủ công** (download/upload) — chấp nhận, nhất quán pattern parallax Colab.
