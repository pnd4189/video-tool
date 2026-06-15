# Brainstorm: 2.5D parallax animation cho ảnh tĩnh truyện (free/offline)

Date: 2026-06-14 · Mode: /brainstorm · Status: POC passed → ready for /ck:plan

## Problem
User muốn ảnh truyện tĩnh có "animation nhẹ" giống 3 video YouTube mẫu, dùng máy cá nhân.

## Finding quan trọng (lật giả định)
3 video mẫu KHÔNG phải ảnh tĩnh động nhẹ — chúng là **hoạt hình 2D đầy đủ**:
- FL2shUbzOBw (Gấu Cute): cutout 2D, nhân vật bước đi (walk cycle).
- QFuZFW7pHGQ / ffarxsSGSoE: donghua/hoạt hình TQ ripped + vietsub/lồng tiếng.
→ Không thể tái tạo từ ảnh tĩnh + chuyển động nhẹ. Cần rig thủ công hoặc AI cloud trả phí.

## Decisions (user-confirmed)
- Fidelity: **ảnh tĩnh động nhẹ** (parallax 2.5D), chấp nhận nhân vật KHÔNG tự cử động.
- Budget: **100% miễn phí, offline**.
- Định hướng: **giữ audio-first**, hình chỉ chống static-penalty + đỡ nhàm (đúng triết lý CLAUDE.md).

## Hardware (đo thực)
- CPU AMD Ryzen 5 7640HS (12 luồng), iGPU Radeon 760M.
- iGPU: 1024 MB VRAM cứng + ~15.4 GB GTT (mượn RAM). RAM hệ thống ~30 GB.
- KHÔNG có NVIDIA/CUDA, KHÔNG có passwordless sudo, không có portaudio.
- ffmpeg system có VAAPI encode (h264_vaapi). venv chính chưa có torch.

## Approach chốt: B — DepthAnythingV2 + parallax FFmpeg/numpy
- DepthFlow (cách A) **bị loại**: hard-dep `pyaudio` cần `portaudio19-dev`, không build được (no sudo), không có wheel. Và không cần thiết.
- Cách B: depth map bằng `depth-anything/Depth-Anything-V2-Small-hf` (transformers, CPU) → parallax bằng inverse-warp (numpy nearest + edge-clamp + zoom nhẹ) → pipe ffmpeg libx264. Tích hợp sạch vào pipeline FFmpeg sẵn có (KISS/DRY).

## POC results (ảnh thật: BÌNH THIÊN SÁCH Chap1/scene_001_4K.jpg, 3840×2160)
- Depth @4K = **83s/ảnh** (chậm vì 4K). Fix: resize 1280px + `torch.set_num_threads(12)` → **0.7s/ảnh**.
- Render parallax 1080p = **28 fps ≈ realtime** trên CPU (numpy thuần, không GPU).
- Look: depth tách lớp sạch (cây/người/nhà/nền), parallax tự nhiên, không lỗ đen (edge-clamp + zoom 1.06).
- 1 tập 40 ảnh ước tính: depth ~30s + render ~thời lượng clip. Không cần GPU.
- POC artifacts (throwaway, /tmp): `/tmp/poc-depth/parallax_poc.py`, `parallax_out2.mp4`, `depth_vis.jpg`, `frame_a/b.jpg`.

## Integration sketch (cho plan)
1. Depth precompute: ảnh → resize ≤1280 → DepthAnythingV2-Small → cache depth map (PNG) cạnh ảnh.
2. Parallax render: thay/bổ sung motion mode trong `render/video_filters.py` (hiện zoompan Ken Burns). 2 lựa chọn impl:
   - (b1) numpy renderer riêng → clip mp4 → nạp qua `storyboard auto --videos-dir` (đã hỗ trợ interleave clip).
   - (b2) FFmpeg-native `displace`/`remap` với depth map → giữ 1 pipeline, đúng kiến trúc tool.
3. Duration: parallax phải khớp scene duration do storyboard tính từ audio (orbit loop theo độ dài scene).
4. Overlay (free, FFmpeg): sương/bụi/grain/light-ray composite thêm nếu muốn.
5. Dependency: thêm `torch` (CPU) + `transformers` vào extras (~600MB). Cân nhắc env/extra riêng để không nặng base.

## Risks
- Edge stretch khi parallax mạnh → giảm bằng zoom crop + giới hạn biên độ (~40-50px@1080p).
- Depth sai trên vài ảnh phức tạp → cho phép fallback về Ken Burns cũ per-scene.
- Inverse-map nearest có thể duplicate pixel ở mép depth → đủ tốt cho audio-first; nếu cần đẹp hơn dùng bilinear/mesh.
- Thêm torch/transformers làm nặng cài đặt → để dạng optional extra.

## Unresolved questions
- Chọn impl b1 (clip) hay b2 (FFmpeg-native)? Đề xuất b2 cho tích hợp lâu dài; b1 nhanh ra mắt.
- Parallax mặc định: orbit (sin/cos) hay chỉ horizontal sway? POC dùng orbit, nhìn ổn.
- Có bật overlay effects ngay phase 1 hay để phase sau?
- Biên độ parallax + zoom mặc định để chuẩn hóa (POC: 45px / zoom 1.06).
