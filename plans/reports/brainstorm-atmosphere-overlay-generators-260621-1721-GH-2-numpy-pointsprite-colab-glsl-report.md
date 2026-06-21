# Brainstorm — Atmosphere overlay generators (đom đóm + tàn lửa bùa + bụi + linh khí)

- Date: 2026-06-21 17:21 (Asia/Bangkok)
- Branch: feat/parallax-2-5d
- Mode: brainstorm (no --html/--wiki)
- Trigger: user thấy `particles` generic chưa hợp truyện ĐẠO SĨ (đêm-quê-ma-hài); muốn đom đóm + overlay bám bối cảnh; hỏi Remotion/Three.js/Hyperframe vs tải sẵn.

## Problem statement
Thư viện overlay CC0 hiện generic (rain/snow/fire/smoke/particles/dust/cosmos), thiếu atmosphere bám-bối-cảnh truyện. Nhu cầu thật: **mở rộng library bằng atmosphere theo GENRE siêu nhiên/linh dị**, tái dùng, rẻ. Đom đóm là ca đầu.

## Scope (đã chốt với user)
4 overlay: **đom đóm, tàn lửa bùa符, bụi lơ lửng, linh khí (qi wisps)**. Tất cả phục vụ job thật (series ĐẠO SĨ), không đầu cơ.

## Ràng buộc đã verify (scout)
- Hợp đồng overlay đơn giản: `particle_input_args` = `-stream_loop -1 -i <mp4>` (overlay_graph.py:145). Bất kỳ MP4 loop được. Atmosphere blend `all_mode=screen` trong `gbrp` RGB, scale+crop về preset (overlay_graph.py:71-75) → nền đen biến mất, chỉ điểm sáng hiện.
- Repo ĐÃ CÓ pattern sinh frame không-dep-mới: `parallax.py:120-130` numpy/PIL → `ffmpeg -f rawvideo -pix_fmt rgb24 -i -` → libx264 mp4.
- Máy: AMD Phoenix1 iGPU, **không NVIDIA**. Repo đã chốt "việc cần GPU → Colab" (parallax DepthFlow, torch-CUDA, upload/download thủ công).
- Library tại `~/.local/share/videotool/overlays/` (durable, dời khỏi ~/.cache 2026-06-21). Naming `{kind}-{src}-{id}.mp4`.
- Node v24 + npx có sẵn nhưng repo KHÔNG có Node project.

## Approaches đã cân nhắc
| Hướng | Pros | Cons | Verdict |
|---|---|---|---|
| Tải free-commercial (Pixabay) | nhanh ~15', free thương mại | loop seam 49' giật; phải lọc black-bg; zero tinh chỉnh | stopgap, không chọn |
| **numpy→ffmpeg generator (in-repo)** | 0 dep mới; seamless loop (sin tuần hoàn); parametric; DRY | viết engine lần đầu | **chọn cho 3 point-sprite** |
| Three.js/Remotion local | quality trần cao | thêm Node+headless WebGL; máy không GPU → software render; quality vô hình khi screen-blend; trái nguyên tắc kênh | loại |
| Three.js/Remotion trên Colab/Kaggle | "GPU cloud" | **headless Chrome WebGL hay rơi SwiftShader (CPU software) trên Colab** dù có GPU → gánh chi phí mà GPU ngồi không; sai công cụ cho offline-GPU | loại |
| **GLSL shader (moderngl/EGL) / torch-CUDA trên Colab** | chạm GPU NVIDIA thật headless; curl-noise flow-field đẹp | thêm pattern Colab | **chọn cho linh khí** |

## Giải pháp cuối (đã user duyệt)
**Pragmatic, trả tiền GPU đúng chỗ nhìn thấy:**
- **Đom đóm + tàn lửa bùa + bụi** = numpy point-sprite engine in-repo (tái dùng pattern parallax.py). 3 preset = 3 bộ tham số (màu/vận tốc/lifecycle/mật độ/glow). Point-sprite không hưởng lợi GPU → numpy đủ đẹp, lại được `enhance.glow` bloom thêm.
- **Linh khí** = GLSL fragment shader (curl-noise flow-field) render trên Colab GPU (moderngl/EGL hoặc torch-CUDA), nhất quán pattern parallax. Đây là hiệu ứng DUY NHẤT GPU thắng rõ (tua sáng thể tích). Dùng `shader` skill để viết GLSL.

### Nguyên tắc kiến trúc (quan trọng)
Generator là **công cụ tạo asset OFFLINE**, KHÔNG nối vào render pipeline. Chạy 1 lần → bỏ mp4 vào `~/.local/share/videotool/overlays/` → pipeline tiêu thụ qua `inputs.particle_overlay` y như mọi clip. Giữ tool Python sạch (không Node, không torch-overlay local).

### Spec output
1920×1080 (pipeline 1080p; library 4K cũ vốn downscale), H264 yuv420p, **nền đen tuyệt đối (0,0,0)**, loop ~15-20s seamless. Tên: `fireflies-gen-01.mp4`, `ember-gen-01.mp4`, `dust-gen-01.mp4`, `qi-gen-01.mp4` (src=`gen`).

### Seamless loop
Mọi chuyển động theo hàm tuần hoàn của `(frame/total)*2π` → frame0 == frameN. Vị trí wrap, nháy = sin, lifecycle phase wrap.

### Engine params (point-sprite)
count, color(rgb), spawn-dist, velocity(drift+jitter), flicker(period,depth), glow(sigma), lifecycle(ember: spawn-rise-fade), loop_seconds, fps=30, size. Mỗi preset = 1 param-set.

### Vị trí script
Standalone `scripts/gen-overlay.py` (numpy/PIL/ffmpeg) — KHÔNG thêm Typer subcommand (tác vụ authoring hiếm chạy, tránh phình CLI). (chốt lại ở plan)

### Doc/memory
Cập nhật mood-map AGENTS.md: đêm/quê→fireflies; đốt bùa/action→ember; nội thất bỏ hoang/cũ→dust; siêu nhiên/linh khí→qi. Cập nhật memory `overlay-fx-library`.

## Risks
- Loop seam nếu phá tuần hoàn → unit test pixel-diff frame0≈frameN.
- Screen-blend washout nếu quá sáng/dày → tinh chỉnh + verify trên 1 frame render thật.
- Colab GLSL/EGL headless setup friction → fallback numpy curl-noise xấp xỉ nếu Colab quá đau.
- Overlay nổi quá → mất tập trung audio (sản phẩm thật). Giữ tinh tế: count/brightness thấp. **Tinh tế > sắc nét.**

## Success criteria
- 4 mp4 trong library; mỗi cái seamless (không thấy seam ở 49'), black-bg, screen-blend sạch (không halo/wash), hợp genre.
- Dùng trong 1 render ĐẠO SĨ thật → người xem cảm nhận nền chìm, không bị phân tâm.
- numpy generators: 0 dep mới, chạy local <2'/clip.

## Next steps (phác phase cho /ck:plan)
1. numpy point-sprite engine + preset đom đóm; verify seam + screen-blend trên frame thật.
2. preset tàn lửa (lifecycle bay lên) + bụi (chậm/mờ).
3. linh khí GLSL shader trên Colab; download + tích hợp library.
4. Cập nhật mood-map AGENTS.md + memory.

## Unresolved
- Script standalone vs Typer subcommand (lean: standalone) — chốt ở plan.
- Colab linh khí: moderngl/EGL vs torch-CUDA — chốt khi prototype.
- Có cần >1 biến thể mỗi kind (-gen-01/-02) không, hay 1 đủ.
