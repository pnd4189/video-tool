# Brainstorm: Colab DepthFlow → local ingest 2.5D parallax (advanced, isolated)

Date: 2026-06-18 · Branch: feat/parallax-2-5d · Status: approved → plan --tdd

## Problem
Muốn parallax 2.5D cho video audio-story (dài 1h40–1h45, ngắn 15–30′) nhưng tận dụng GPU Colab,
giữ workflow `/make-video` hiện tại nguyên vẹn (đang dùng chính). Colab xuất clip chuyển động →
user tải về → up gdrive thủ công → render full video trên local (Ryzen 12-thread).

## Scout findings (đã đọc source)
- `render/parallax.py`: parallax = sinh 1 mp4/ảnh, thay still, motion=static, fallback Ken Burns per scene.
- Cache key dính `path+mtime_ns` (`parallax.py:155`) → KHÔNG portable cross-machine; `parallaxize_timeline`
  raise nếu thiếu torch trước cả khi check cache → đường "copy cache" tệ.
- **Reframe quan trọng:** depth rẻ (~0.7s/ảnh @1280px), nút thắt thật là **warp numpy ~30fps CPU** + encode
  (1h45 ≈ 85–90′ warp). Warp là numpy-CPU → đem nguyên code lên Colab thì GPU chỉ offload depth (phần rẻ),
  warp vẫn CPU; Colab free 2-vCPU còn chậm hơn Ryzen. ⇒ Colab chỉ đáng nếu warp chạy GPU → **dùng DepthFlow**
  (GPU, `Colab/v3_depthflow_colab.py` đã prototype; quyết định cũ "DepthFlow chỉ bản Colab").
- Render đã loop+trim video media: `commands.py:91` / `segmented.py:72` dùng `-stream_loop -1 -t dur`.
- Clip orbit hiện tại tuần hoàn (sin/cos) → loopable.
- Chap 8: 115 ảnh, Image/ Video/ Music/ CTA voice/ + thumbnail + ảnh end, chưa có job.yaml.

## Decisions (chốt qua /ask + /brainstorm)
- Colab engine = **DepthFlow GPU** (giữ numpy-local `enhance.parallax` làm đường độc lập, không đụng).
- Transport = **thủ công** (user tải Colab → up gdrive). KHÔNG auto rclone sync vòng này.
- **Slash command riêng** (đề xuất `/parallax-video`); `/make-video` giữ nguyên 100%.
- Contract clip (tư vấn, user uỷ quyền) = **loopable 1:1 theo ảnh, tách rời timing** (xem dưới).
- Plan mode = **--tdd** (vì parallax-link động vào media_path timeline).

## Approaches evaluated
| Contract | Pros | Cons | Verdict |
|---|---|---|---|
| **Loopable clip 1:1/ảnh, tách timing** | local `-stream_loop -1 -t dur` tự lặp+cắt; KHÔNG manifest/lệch giờ; transport nhẹ (~350MB); fallback per-ảnh | scene dài thấy orbit lặp; cần clip tuần hoàn để loop liền | ✅ CHỌN |
| Bake đúng duration/scene qua manifest | chính xác, không lặp | coupling chặt (đổi job.yaml/voice = lệch); transport nhiều GB; dễ lỗi | ❌ |
| Copy `.videotool/parallax-cache` | tái dùng cơ chế sẵn | key path+mtime không portable; local vẫn cần torch | ❌ |

## Chosen architecture
```
COLAB (GPU DepthFlow)                  LOCAL  /parallax-video <folder>
Image/<stem>.jpg → clip:               1. stage (rclone)
 • 1080p, orbit TUẦN HOÀN (loop)       2. init-job + storyboard auto  (reuse)
 • dài cố định ~8–12s                  3. parallax-link: scene-ảnh → Parallax/<stem>.mp4
 • tên = <stem>.mp4                        (thiếu → giữ still + Ken Burns)
output → Parallax/ (tải→up gdrive)     4. validate → render → package (reuse; loop+trim sẵn có)
```
Robustness ("local nuốt không lỗi"): tách timing → không lệch giờ; fallback per-ảnh không crash;
render tự chuẩn hoá res/fps/colorspace; local KHÔNG cần torch. Orbit phải tuần hoàn để stream_loop liền;
nếu không → ping-pong loop (vòng sau).

## Code touchpoints (nhỏ, cô lập)
- Reuse (không đụng): `compile_timeline`, storyboard, render, CTA, subtitles, showwaves, atmosphere, package, `/make-video`.
- MỚI 1: CLI `videotool parallax-link <job> --clips-dir Parallax` — swap media_path scene-ảnh → clip cùng stem; thiếu thì giữ. (~30–40 dòng, lõi duy nhất)
- MỚI 2: skill `/parallax-video` — orchestrate stage→init→storyboard→parallax-link→validate→render→package.
- MỚI 3: Colab DepthFlow batch script (phỏng `v3_depthflow_colab.py`): Image/→Parallax/ clip loopable 1080p tên-theo-stem, CHỈ sinh clip.
- MỚI 4: AGENTS.md mục riêng + memory.

## Scope OUT
auto rclone sync; GPU grid_sample port repo numpy; manifest duration-baked; ping-pong loop (chỉ nếu cần);
`enhance.parallax` numpy-local giữ nguyên.

## Risks
- DepthFlow Colab env/session mong manh (user-side, POC 1 lần).
- Tuning biên độ DepthFlow nhẹ để tránh méo rìa.
- Transport ~115 clip thủ công (~350MB nhờ loopable ngắn).
- Loop seam nếu clip không tuần hoàn → POC kiểm + ping-pong dự phòng.

## Success criteria
- `/parallax-video <Chap 8>` ra mp4 16:9 h264/aac đúng res, mọi scene-ảnh chạy clip parallax (hoặc Ken Burns fallback nếu thiếu clip), subtitles/showwaves/atmosphere vẫn đúng.
- `parallax-link` map đúng stem→clip; thiếu/sai tên không crash.
- `/make-video` + test suite không hồi quy.
- DepthFlow Colab script ra clip 1080p tuần hoàn, tên theo stem, loop local không giật.

## Open questions
- DepthFlow orbit có tuần hoàn-seamless theo cấu hình nào? (POC quyết stream_loop vs ping-pong)
- Độ dài clip cố định tối ưu (8 / 10 / 12s) cho scene trung bình ~55s? (POC thẩm mỹ)
- Tên slash command cuối: `/parallax-video` hay khác?
