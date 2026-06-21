---
phase: 1
title: Point-sprite engine + fireflies preset
status: completed
priority: P1
dependencies: []
effort: ''
---

# Phase 1: Point-sprite engine + fireflies preset

## Overview
Xây engine sinh overlay point-sprite (đốm sáng glow trên nền đen) bằng numpy→ffmpeg, tái dùng pattern `parallax.py`; ra preset đầu tiên là đom đóm. Thiết lập + verify hợp đồng seamless-loop + screen-blend để 2 preset sau (phase 2) chỉ là tham số.

## Requirements
- Functional: 1 script standalone sinh mp4 overlay từ một bộ tham số preset. Preset `fireflies` → `fireflies-gen-01.mp4`.
- Non-functional: 0 dependency mới (numpy, PIL, ffmpeg đã có); chạy local < 2 phút/clip; nền đen tuyệt đối; loop seamless (frame0 == frameN).

## Architecture
- **Vị trí:** `scripts/gen_overlay.py` (standalone authoring tool, KHÔNG thêm Typer subcommand — tác vụ hiếm chạy, tránh phình CLI surface).
- **Render loop = pattern parallax.py:** `subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24","-s",f"{w}x{h}","-r",str(fps),"-i","-","-an","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",str(out)], stdin=PIPE)`; mỗi frame ghi `buf.tobytes()` (uint8 HxWx3 rgb24).
- **Point-sprite accumulation:** buffer float32 HxWx3 khởi tạo 0 (đen tuyệt đối). Mỗi particle splat 1 gaussian kernel nhỏ (precompute 1 lần) **cộng dồn** (additive) vào buffer → clip [0,255] → uint8. Additive trên nền đen ăn khớp screen-blend.
- **Seamless loop (cốt lõi):** mọi chuyển động là hàm tuần hoàn của `t = i/N` (N = tổng frame = fps × loop_seconds). Đom đóm lượn = tổng vài sin (Lissajous) theo `2π·t` per-particle phase → vị trí frame0 == frameN. Nhấp nháy = `sin(2π·t·k + φ)`. Không dùng random-walk tích lũy (phá tuần hoàn).
- **Tham số preset (dataclass/dict):** `size=(1920,1080)`, `fps=30`, `loop_seconds=18`, `count`, `color_rgb`, `glow_sigma`, `drift_amp_px`, `drift_freqs`, `flicker_period`, `flicker_depth`, `brightness`, `spawn_seed`. Preset `fireflies`: count thưa (~60-90), màu vàng-lục ấm (~#cfe06a), trôi chậm lượn, nháy mềm, hơi bay lên, brightness vừa.
- **Output:** ghi thẳng `~/.local/share/videotool/overlays/fireflies-gen-01.mp4` (hoặc `--out`); tên theo `{kind}-gen-{id}.mp4`.

## Related Code Files
- Create: `scripts/gen_overlay.py` (engine + preset registry + CLI argparse: `--preset`, `--out`, `--id`)
- Create: `tests/test_overlay_gen.py` (unit test seam + black-bg, render clip ngắn N nhỏ)
- Reference (đọc, không sửa): `src/videotool/render/parallax.py` (ffmpeg pipe), `src/videotool/render/overlay_graph.py:63-76` (cách atmosphere được scale+crop+screen-blend)

## Implementation Steps
1. Tạo `scripts/gen_overlay.py`: argparse (`--preset fireflies`, `--out PATH`, `--id 01`, optional `--seconds`/`--fps`).
2. Viết `_gaussian_sprite(sigma) -> np.ndarray` (kernel vuông nhỏ, đỉnh 1.0).
3. Viết engine `render_pointsprite(params) -> writes frames to ffmpeg`: khởi tạo particle (pos seed, phase, freq, color); vòng `for i in range(N): t=i/N`; reset buffer 0; với mỗi particle tính pos tuần hoàn + flicker, additive-splat sprite×color×brightness×flicker; clip→uint8→`ff.stdin.write(buf.tobytes())`.
4. Preset registry `PRESETS = {"fireflies": {...}}`; map preset→params.
5. Chạy thử sinh `fireflies-gen-01.mp4`; mở bằng ffprobe xác nhận 1920×1080 h264 yuv420p ~18s.
6. **Verify screen-blend trên frame THẬT:** lấy 1 frame của 1 video story (hoặc ảnh tối), ffmpeg `blend=all_mode=screen` trong gbrp với 1 frame overlay → kiểm đốm sáng hiện đúng, nền không wash, không halo. Tinh chỉnh `brightness`/`glow_sigma`/`count` nếu washout.
7. Viết `tests/test_overlay_gen.py`: (a) **seam** — render N=30 frame ra buffer list, assert mean(|frame0-frameN_wrap|) < ngưỡng nhỏ; (b) **black-bg** — assert median pixel toàn frame ≈ 0 (đốm thưa nên nền là đa số).

## Success Criteria
- [ ] `scripts/gen_overlay.py --preset fireflies` sinh `fireflies-gen-01.mp4` (1920×1080, h264 yuv420p, ~18s) < 2 phút.
- [ ] Loop seamless: test seam pass (frame0 ≈ frameN).
- [ ] Nền đen tuyệt đối: test black-bg pass.
- [ ] Screen-blend trên frame thật: đốm đom đóm hiện rõ, nền không wash/magenta, không halo vuông quanh sprite.
- [ ] 0 dependency mới (chỉ numpy/PIL/ffmpeg đã có).

## Risk Assessment
- **Seam lộ** nếu lỡ dùng random-walk tích lũy → bắt buộc mọi motion là hàm của `t=i/N`; test seam chặn.
- **Halo vuông** quanh sprite nếu kernel cắt cứng → gaussian đủ rộng + viền kernel ≈ 0.
- **Washout** khi screen-blend nếu quá sáng/dày → giảm brightness/count; verify bước 6 trước khi chốt.
- **Sprite splat ra biên** → clip chỉ số hoặc pad buffer rồi crop.
