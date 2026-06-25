# Video Tool — Audio-First YouTube Video Generator

**Video Tool** là một công cụ dòng lệnh Python (CLI) biến **file âm thanh + hình ảnh + nhạc nền** thành video YouTube dài hạn (16:9) hoặc Shorts (9:16) **tự động, không cần CapCut**.

Được tối ưu cho các kênh dịch truyện âm thanh (Bình Thiên Sách, Đạo Sĩ, v.v.): khả năng tạo 1 video trong ~1 giờ, không yêu cầu kỹ năng chỉnh sửa video.

## Tính năng chính

| Tính năng | Mô tả |
|-----------|-------|
| **Render nhanh** | Tier light (mặc định): không mã hóa lại, chỉ xếp chồng → ~1h cho video 1h |
| **Phụ đề thông minh** | Script được căn chỉnh vào thời gian whisper, không dựa trên segment |
| **Hiệu ứng FX** | 5 loại mood + overlay khí quyển (mưa/tuyết/lửa/lửa dương vật) |
| **2.5D Parallax** | Stills → Ken Burns hoặc Deep DepthFlow (GPU Colab) |
| **Chương tự động** | Whisper transcript → YouTube chapter timestamps |
| **B-roll interleave** | Video clips trộn với hình ảnh theo thứ tự |
| **Sidechain audio** | Nhạc tự động giảm âm lượng dưới giọng nói |

## Cài đặt (Minimal)

```bash
cd /home/dung/VIBE_CODING/video-tool
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[ai]  # Cài với faster-whisper
```

**Kiểm tra setup:**
```bash
.venv/bin/videotool doctor
ffprobe --version  # Đảm bảo FFmpeg 6.1+
```

## Cách sử dụng (Quick Start)

### Bước 1: Chuẩn bị folder asset

```
my-video/
├── voice.wav
├── media/
│   ├── scene-001.jpg
│   └── ...
├── Video/              # Tùy chọn
├── music/              # Tùy chọn (để ở thư mục)
└── Ảnh end video/
```

### Bước 2: Chạy pipeline

```bash
cd /home/dung/VIBE_CODING/video-tool
VT=.venv/bin/videotool
JOB_DIR="path/to/my-video"
JOB="$JOB_DIR/job.yaml"

# 1. Init
$VT init-job "$JOB_DIR" --voice voice.wav --media media --music music

# 2. Tắt caption + allow-missing-local
sed -i \
  -e 's/policy: licensed-only/policy: allow-missing-local/' \
  -e "/captions:/,/^[^ ]/ s/mode: srt-only/mode: off/" \
  "$JOB"

# 3. Auto-storyboard
$VT storyboard auto "$JOB" --images-dir "$JOB_DIR/media" --videos-dir "$JOB_DIR/Video"

# 4. Validate + render + package
$VT validate "$JOB"
$VT render "$JOB" --preset youtube-16x9
$VT package "$JOB"
```

**Output:** `$JOB_DIR/outputs/youtube-16x9.mp4` + metadata

## Tier: Light vs Full

| Aspect | Light | Full |
|--------|-------|------|
| Re-encode | Không | Có (1 lần) |
| Motion | Ken Burns | Ken Burns |
| Subtitle | Không (YouTube auto) | Có (whisper align) |
| FX | Không | Mood + atmosphere |
| Tốc độ | ~1h cho 1h audio | ~2–3h |

## 2.5D Parallax (Tùy chọn)

**Local (CPU):** `pip install -e .[parallax]` → set `enhance.parallax: true` trong job.yaml

**Colab (GPU):** Chạy `Colab/v4_depthflow_clips_colab.py` → tải `Parallax/` → `videotool parallax-video $JOB_DIR`

## Hiệu ứng FX & Mood

```yaml
enhance:
  mood: melancholy              # clean/melancholy/cozy/horror/action
  atmosphere: true
  particle_overlay: rain-forfilmcreation-001.mp4
```

**Mood map:** clean/melancholy/cozy/horror/action

**Atmosphere:** Chọn từ `~/.local/share/videotool/overlays/`

## Shorts (9:16)

Mặc định 16:9 only. Thêm Shorts khi yêu cầu:

```yaml
outputs:
  - preset: youtube-16x9
  - preset: shorts-9x16
```

Render: `$VT render "$JOB" --all`

## CLI Commands

```
doctor          # Kiểm tra FFmpeg + Python
init-job        # Tạo job skeleton
validate        # Kiểm tra job.yaml
render          # Render video (--preset, --all, --enhance)
transcribe      # Whisper → captions.srt + chapters.json
storyboard auto # Xếp hình ảnh/clips tự động
parallax-link   # Link Colab parallax clips
parallax-video  # Full pipeline cho /parallax-video
package         # Tạo YouTube package (description, thumbnails)
batch           # Render nhiều job song song
```

## Troubleshooting

| Vấn đề | Giải pháp |
|--------|----------|
| ffprobe not found | `apt install ffmpeg` |
| ImportError | Tạo lại venv: `rm -rf .venv && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e .` |
| Render bị treo | Tăng disk temp hoặc chia video |
| Glow làm mờ fireflies | Thêm `enhance.glow: false` |

## Tài liệu chi tiết

- **[docs/project-overview-pdr.md](./docs/project-overview-pdr.md)** — Product intent, target user
- **[docs/deployment-guide.md](./docs/deployment-guide.md)** — Setup variants
- **[docs/system-architecture.md](./docs/system-architecture.md)** — Render flow, audio chain
- **[docs/code-standards.md](./docs/code-standards.md)** — Python style, testing
- **[docs/design-guidelines.md](./docs/design-guidelines.md)** — Motion, loudness, subtitle timing
- **[CLAUDE.md](./CLAUDE.md)** — Full CLI reference + pitfalls

## GUI (Thử nghiệm)

```bash
.venv/bin/videotool gui
# Truy cập http://localhost:8000
```

## Verify

```bash
ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 outputs/youtube-16x9.mp4
# Expected: h264, aac, 1920x1080

.venv/bin/python -m pytest -q
# Expected: 155+ pass
```

---

**Tóm tắt:** `voice.wav + media/` → `/make-video` → `youtube-16x9.mp4` trong ~1h. Không cần kỹ năng. Xem [CLAUDE.md](./CLAUDE.md) chi tiết CLI.
