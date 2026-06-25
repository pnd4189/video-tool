# Deployment & Installation Guide

## Prerequisites

### System Requirements

| Item | Requirement | Check |
|------|-------------|-------|
| Python | 3.12+ | `python3.12 --version` |
| FFmpeg | 6.1+ | `ffmpeg -version` && `ffprobe -version` |
| Disk | 2GB free (cache + temp outputs) | `df -h` |
| OS | Linux/macOS/Windows (WSL2) | Any POSIX shell |

### Optional Dependencies

- **Faster-Whisper (STT):** Requires `[ai]` extra (auto-installed below)
- **DepthAnything V2 (Local parallax):** Requires `[parallax]` extra + `torch` CPU build
- **Colab GPU (DepthFlow):** Requires Google Colab account (notebook at `Colab/v4_depthflow_clips_colab.py`)

---

## Installation Variants

### Variant 1: Minimal (Light Jobs Only)

**Use when:** Creating videos without subtitles, mood FX, or parallax.

```bash
cd /home/dung/VIBE_CODING/video-tool
python3.12 -m venv .venv
source .venv/bin/activate  # or: . .venv/bin/activate on bash
pip install -e .
```

**Verify:**
```bash
.venv/bin/videotool doctor
ffprobe -version
```

**Size:** ~500MB (venv + code)

### Variant 2: Full-Tier (Subtitles + Mood FX)

**Use when:** Creating videos with subtitles, mood effects, atmosphere overlays.

```bash
cd /home/dung/VIBE_CODING/video-tool
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[ai]  # Includes faster-whisper
```

**First run (model download):**
```bash
# Download Whisper base model (~1.5GB, cached offline)
python -c "from videotool.ai.faster_whisper_adapter import initialize_whisper; initialize_whisper()"
# Or let transcribe download it on first use
```

**Size:** ~2GB (venv + code + Whisper model cache at `~/.cache/videotool/models/`)

### Variant 3: Parallax Local (CPU 2.5D Animation)

**Use when:** Stills should animate as 3D parallax via DepthAnything V2 (CPU, offline).

```bash
cd /home/dung/VIBE_CODING/video-tool

# 1. Create venv
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install torch CPU build (NOT GPU)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 3. Install video-tool with parallax extra
pip install -e .[parallax,ai]
```

**First run (model download):**
```bash
# DepthAnything V2-Small model (~350MB)
python -c "from videotool.render.parallax import initialize_depth_model; initialize_depth_model()"
```

**Size:** ~3GB (venv + code + Whisper + DepthAnything models)

**Note:** First parallax job takes ~2 min per still (GPU would be ~10s). Subsequent jobs reuse cache.

### Variant 4: Parallax Colab (GPU DepthFlow Offload)

**Use when:** GPU unavailable locally but want best-quality depth parallax.

```bash
# 1. Install minimal (no parallax extra needed)
cd /home/dung/VIBE_CODING/video-tool
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[ai]

# 2. Run Colab notebook
# → Open Google Colab: https://colab.research.google.com/
# → Upload Colab/v4_depthflow_clips_colab.py
# → Mount your asset folder (gdrive or local)
# → Run cells → download Parallax/ folder

# 3. Upload Parallax/ beside asset folder locally
# → then run /parallax-video locally (no torch needed)
```

**Workflow:**
```bash
JOB_DIR="/path/to/asset/folder"  # Contains voice.wav, media/, music/, Parallax/
.venv/bin/videotool parallax-video "$JOB_DIR"
```

---

## Post-Installation Verification

### Step 1: Doctor Check

```bash
.venv/bin/videotool doctor
```

Expected output:
```
✓ Python: 3.12.0
✓ FFmpeg: 6.1.0
✓ Pydantic: 2.7.0
✓ Faster-Whisper: available (if [ai] extra installed)
✓ Torch: available (if [parallax] extra installed)
```

### Step 2: First Small Job

```bash
mkdir -p /tmp/test-video
cd /tmp/test-video

# Create dummy voice (3 seconds of silence)
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 3 -q:a 9 -acodec libmp3lame voice.wav

# Create dummy image
ffmpeg -f lavfi -i color=c=blue:s=1920x1080:d=1 -frames:v 1 image.jpg

mkdir media music
mv image.jpg media/scene-001.jpg
echo "dummy" > music/bg.txt  # If no actual music

# Run pipeline
JOB_DIR=/tmp/test-video
VT=/home/dung/VIBE_CODING/video-tool/.venv/bin/videotool
JOB="$JOB_DIR/job.yaml"

$VT init-job "$JOB_DIR" --voice voice.wav --media media --music music
sed -i \
  -e 's/policy: licensed-only/policy: allow-missing-local/' \
  -e "/captions:/,/^[^ ]/ s/mode: srt-only/mode: off/" \
  "$JOB"

$VT storyboard auto "$JOB" --images-dir "$JOB_DIR/media"
$VT validate "$JOB"
$VT render "$JOB" --preset youtube-16x9
$VT package "$JOB"

ls -lh "$JOB_DIR/outputs/"
```

Expected: `youtube-16x9.mp4` (~5MB for 3s video)

### Step 3: Verify Codec

```bash
ffprobe -v error -show_entries stream=codec_name,width,height -of csv=p=0 /tmp/test-video/outputs/youtube-16x9.mp4
# Expected: h264,aac,1920,1080
```

---

## Customization & Configuration

### Motion Constants

Edit `src/videotool/render/video_filters.py`:

```python
ZOOM_AMPLITUDE = 0.30      # Ken Burns zoom speed (0.12 → 0.30 default)
PAN_ZOOM = 1.22            # Zoom factor (was 0.95)
```

**Don't lower without checking with user.** Decided 2026-05-28.

### Mood Presets

Edit `src/videotool/core/job_spec.py`, `MOODS` dict:

```python
MOODS = {
    'clean': {...vignette settings...},
    'melancholy': {...grain + vignette...},
    # Add new moods here
}
```

### SFX Libraries

Place MP3 files (or WAV) in `~/.local/share/videotool/sfx/{channel-name}/`:

```
~/.local/share/videotool/sfx/
├── binh-thien/
│   ├── sword-clash.mp3
│   ├── door-open.mp3
│   └── ...
└── dao-si/
    ├── magic-spell.mp3
    └── ...
```

Loudness range: −11 to −47 dB (normalize per cue). Density rules in `/make-video` workflow.

### Atmosphere Overlays

CC0 library at `~/.local/share/videotool/overlays/`:

```
~/.local/share/videotool/overlays/
├── rain-forfilmcreation-001.mp4
├── snow-forfilmcreation-002.mp4
├── fire-fxelements-003.mp4
├── fireflies-gen-001.mp4         # Generated via scripts/gen_overlay.py
├── qi-gen-001.mp4                # Generated via Colab/qi_wisps_overlay_colab.py
└── ...
```

**Generate locally:**
```bash
.venv/bin/python scripts/gen_overlay.py --preset fireflies --output fireflies-gen-001.mp4
.venv/bin/python scripts/gen_overlay.py --preset ember
.venv/bin/python scripts/gen_overlay.py --preset dust
```

**Generate on Colab (GLSL qi-wisps):**
- Upload `Colab/qi_wisps_overlay_colab.py`
- Run on GPU → download `qi-gen-*.mp4`

---

## Troubleshooting

### Issue: `ffprobe: command not found`

**Solution:**
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Verify
ffprobe -version
```

### Issue: `ImportError: No module named 'videotool'`

**Cause:** Venv not activated or not in correct directory.

**Solution:**
```bash
deactivate  # Exit any venv
cd /home/dung/VIBE_CODING/video-tool
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Issue: Faster-Whisper not installed

**Cause:** Missing `[ai]` extra.

**Solution:**
```bash
source .venv/bin/activate
pip install -e .[ai]
```

### Issue: Render stalls or hangs

**Cause:** Not enough disk space for temp files, or long video segment.

**Solution:**
1. Check disk: `df -h`
2. If <1GB free, delete `~/.cache/videotool/temp/` (safe to delete)
3. For very long videos (>2h), split into chapters and batch-render

### Issue: Whisper transcription stalls for 1+ minute

**Cause:** First run downloading model from Hugging Face Hub (~1.5GB).

**Solution:**
```bash
# Pre-download to avoid HF-Hub timeout
python -c "
from videotool.ai.faster_whisper_adapter import initialize_whisper
initialize_whisper()
"
# Then transcribe will use local cache
```

### Issue: Parallax depth fails → falls back to Ken Burns

**Cause:** DepthAnything model not initialized, or invalid image.

**Solution:**
```bash
# Pre-initialize on first job
python -c "
from videotool.render.parallax import initialize_depth_model
initialize_depth_model()
"

# Check image is valid
ffprobe your-image.jpg
```

### Issue: Glow effect washes out fireflies overlay

**Cause:** `mood=horror` auto-enables glow (brightness boost) → overlays fade.

**Solution:**
Add to job.yaml:
```yaml
enhance:
  mood: horror
  glow: false     # Disable glow when atmosphere on
  atmosphere: true
  particle_overlay: fireflies-gen-001.mp4
```

### Issue: Render output video has magenta tint

**Cause:** Screen-blend overlay running in yuv420p instead of RGB.

**Solution:**
Already fixed (2026-06-18). If upgrading from older version, pull latest code.

---

## Development Setup

### For Contributors

```bash
cd /home/dung/VIBE_CODING/video-tool
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,ai,parallax]'
```

**Run tests:**
```bash
.venv/bin/python -m pytest -q
# Expected: 155+ passing
```

**Code style:**
```bash
.venv/bin/black src/ tests/
.venv/bin/ruff check src/ tests/
```

---

## Performance Tuning

### CPU-Only Render (Default)

- **Encoder:** `libx264-balanced` (CRF 23, preset veryfast)
- **Throughput:** ~1 frame/sec on AMD Ryzen 5 7640HS (real-time for 1h video)
- **Memory:** ~800MB–1.5GB during render

### Multi-Job Parallel Rendering

```bash
# Batch 4 jobs in parallel (limited by CPU cores)
.venv/bin/videotool batch \
  job1/job.yaml \
  job2/job.yaml \
  job3/job.yaml \
  job4/job.yaml \
  --workers 4
```

### Disk I/O

- **SSD preferred:** Temp clips written to `<job>/.videotool/temp/` during segmented render
- **HDD acceptable:** Slower clips, but still <3h total for 1h video on modern HDD

---

## Upgrade & Rollback

### In-Place Upgrade

```bash
cd /home/dung/VIBE_CODING/video-tool
git pull origin feat/parallax-2-5d
pip install -e . --upgrade
.venv/bin/videotool doctor
```

### Safe Rollback

```bash
git log --oneline  # Find commit before breakage
git checkout <commit-hash>
pip install -e . --force-reinstall
```

---

## Getting Help

| Resource | Purpose |
|----------|---------|
| `videotool doctor` | Check environment |
| `videotool --help` | CLI command reference |
| `[CLAUDE.md](../CLAUDE.md)` | Full workflow + pitfalls |
| `[docs/system-architecture.md](./system-architecture.md)` | Render flow, tier paths |
| `[docs/design-guidelines.md](./design-guidelines.md)` | Motion, loudness, subtitle |
| Email: pndmmo@gmail.com | Owner contact |

---

## Diskspace & Caching

### Cache Directories

```
~/.cache/videotool/
├── models/
│   └── faster-whisper-base/  # ~1.5GB (SRT transcription)
├── temp/                      # ~2× output size (safe to delete)
└── ...

~/.local/share/videotool/
├── overlays/                  # ~5GB (CC0 atmosphere library, durable)
├── sfx/                       # ~100MB (SFX per-channel)
└── ...
```

**Reclaim disk:**
```bash
rm -rf ~/.cache/videotool/temp/    # Safe (re-renders if needed)
rm -rf ~/.cache/videotool/models/  # Safe (re-downloads model on next transcribe)
# DO NOT delete ~/.local/share/videotool/overlays/ without backup
```

---

## Next Steps

1. **Read:** [docs/system-architecture.md](./system-architecture.md) — understand render flow
2. **Read:** [CLAUDE.md](../CLAUDE.md) — full CLI reference + confirmed decisions
3. **Try:** First small job (see "Step 2" above)
4. **Explore:** Full-tier with mood FX, then parallax
