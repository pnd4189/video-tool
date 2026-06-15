---
slug: local-parallax-2-5d-integration
status: done
created: 2026-06-14
completed: 2026-06-15
owner: dung
source: plans/reports/from-brainstorm-to-planner-260614-1956-parallax-2-5d-still-animation-report.md
---

# Plan: tích hợp parallax 2.5D vào video-tool (bản local, free/offline)

## Mục tiêu
Thêm motion "parallax 2.5D" (ảnh có chiều sâu, trôi theo depth) như **opt-in** vào pipeline
render hiện tại, chạy CPU offline trên máy local. Giữ Ken Burns làm mặc định.

## Quyết định kiến trúc (chốt từ brainstorm + scout)
- **Cách B2-as-precompute, KHÔNG hack `displace` vào `scene_filter`.** FFmpeg thuần rất khó
  warp per-pixel theo depth động. Pipeline đã nhận scene video clip (`job_spec.py:77`,
  nhánh clip trong `video_filters.py:scene_filter` + interleave). → render ảnh→clip parallax
  rồi đi theo đường clip sẵn có. KISS/DRY.
- **Backend = torch CPU** (depth cần torch+transformers; dùng luôn torch cho warp bilinear).
- **Opt-in qua `enhance.parallax`** (giống visualizer/subtitles), không bật mặc định.
- Params verify từ POC: depth input ≤1280px, parallax 45px, zoom 1.06, orbit sin/cos.
  Depth @1280+12threads ≈ 0.7s/ảnh; warp ≈ realtime CPU @1080p.
- **Fallback**: ảnh nào depth lỗi → giữ nguyên zoompan cũ, không chặn render.
- Dep nặng → **optional extra** `videotool[parallax]`, import có guard + báo lỗi rõ.

## Điểm tích hợp (scout)
- `src/videotool/core/job_spec.py:124 EnhanceSpec` — thêm field `parallax: bool`.
- `src/videotool/core/services.py` — chèn bước precompute giữa storyboard/validate và render.
- `src/videotool/render/video_filters.py:56` (nhánh clip) — dùng lại nguyên, không sửa.
- `src/videotool/render/parallax.py` — **module mới** (depth + warp + cache).
- `pyproject.toml:18 [project.optional-dependencies]` — thêm extra `parallax`.
- POC nguồn tham chiếu: `/tmp/poc-depth/parallax_poc.py` (logic đã chạy thật).

---

## Phase 0 — Scaffolding + deps
**File:** `pyproject.toml`, `src/videotool/render/parallax.py` (skeleton)
- Thêm `[project.optional-dependencies] parallax = ["torch", "transformers", "pillow", "numpy"]`.
- Tạo `render/parallax.py` với import torch/transformers **trong hàm** (lazy) + thông báo
  `PARALLAX_MISSING_MSG` khi thiếu extra.
- `videotool doctor`: thêm dòng báo parallax extra có/không (optional).
- ✅ Done: `pip install -e .[parallax]` chạy; `doctor` không vỡ khi thiếu torch.

## Phase 1 — Core depth + warp (port POC)
**File:** `src/videotool/render/parallax.py`
- `estimate_depth(image_path) -> np.ndarray`: resize ≤1280, DepthAnythingV2-Small
  (cache model qua HF_HOME mặc định), `torch.set_num_threads`, trả depth 0..1. Cache depth
  ra `<workspace>/.parallax-cache/<hash>.npy` để tái dùng.
- `render_parallax_clip(image_path, duration, fps, w, h, out_path, *, parallax_px=45, zoom=1.06)`:
  torch `grid_sample` bilinear orbit (logic POC), pipe ffmpeg libx264. Trả `out_path`.
- Hằng số mặc định ở đầu module (PARALLAX_PX, ZOOM, DEPTH_MAX_SIDE) — comment "why".
- ✅ Done: gọi tay trên 1 ảnh thật ra clip mp4 đúng thời lượng, không lỗ đen.

## Phase 2 — Tích hợp pipeline (precompute pass)
**File:** `src/videotool/core/job_spec.py`, `src/videotool/core/services.py`
- `EnhanceSpec.parallax: bool = False` + thêm "parallax" vào `ENHANCE_FEATURES`.
- Trong services render flow: nếu `enhance.parallax` → sau khi timeline có duration,
  với mỗi scene là ẢNH: render clip parallax (đúng `scene.duration`, preset w/h/fps),
  đổi `scene.media_path` → clip, `motion="static"` (clip tự chạy). Scene clip gốc giữ nguyên.
- Bọc try/except mỗi scene → lỗi thì log + giữ ảnh+zoompan cũ (fallback).
- Cache clip theo (image hash, duration, params) để render lại không làm lại.
- ✅ Done: job bật `enhance.parallax` render ra video parallax; tắt thì y như cũ.

## Phase 3 — CLI / wiring
**File:** `src/videotool/cli/main.py` (+ storyboard/render seam)
- `render` tự đọc `enhance.parallax` (không cần flag mới). Tùy chọn: cờ `--parallax` ghi đè bật.
- (tùy) `videotool parallax <image> <out> --duration N` để test nhanh 1 ảnh.
- ✅ Done: `videotool render JOB` tôn trọng `enhance.parallax`.

## Phase 4 — Test + verify
**File:** `tests/`
- Unit: depth cache hit/miss; param defaults; fallback khi depth raise.
- Integration: job nhỏ (2–3 ảnh + voice ngắn) bật parallax → render → `ffprobe` xác nhận
  h264/aac/1920x1080 + duration khớp voice.
- `pytest -q` vẫn ≥ baseline (66+), không hồi quy đường Ken Burns.
- ✅ Done: tests xanh, ffprobe đúng.

## Docs (sau khi code)
- `CLAUDE.md`: thêm pitfall (parallax = opt-in, cần extra, CPU ~0.7s/ảnh depth) + decision dòng ngày.
- `docs/codebase-summary.md`: ghi module `render/parallax.py` + precompute step.

## Rủi ro & giảm thiểu
- Edge stretch parallax mạnh → giữ zoom crop 1.06 + giới hạn px ≤ ~50.
- Depth sai ảnh phức tạp → fallback zoompan per-scene (đã có).
- torch CPU nặng (~600MB) → optional extra, không vào base.
- Thời gian render tập dài tăng (depth ~0.7s/ảnh + warp realtime) → chấp nhận, vẫn offline.
- Inverse-warp nearest/bilinear có duplicate mép → đủ cho audio-first; mesh để sau nếu cần.

## Unresolved questions
- Opt-in: `enhance.parallax` (đề xuất) — đồng ý không, hay muốn cả `motion="parallax"` per-scene?
- Có cần `videotool parallax` standalone để test, hay chỉ qua render?
- Cache clip parallax đặt ở `<workspace>/.parallax-cache` hay `outputs/`? (đề xuất workspace tmp)
- Bật overlay (sương/bụi) chung phase này hay tách plan sau? (đề xuất tách — YAGNI)

## Overlay effects — menu cho plan TÁCH sau (reuse `render/overlay_graph.py`)
Đã có: bụi (`assets/overlays/dust.mp4`), grain/noise, progress bar, showwaves/visualizer.
Thêm được (FFmpeg/CPU, free):
- Particle (asset loop, blend screen): sương mù, tuyết, mưa, cánh hoa/lá rơi, đom đóm, tàn lửa, bokeh, light leak.
- Filter thuần: vignette, color-grade/LUT (curves/lut3d), god rays, glow/bloom, light flicker, chromatic nhẹ.
- Transition: xfade dissolve/fade-to-black/whip-blur.
- Camera: handheld shake nhẹ.
Khuyến nghị bộ tối thiểu: sương + vignette + grain + color-grade nhẹ. Mưa/tuyết/cánh hoa theo mood per-scene.
