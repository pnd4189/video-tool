# Project Overview & Product Development Requirements

## Product Intent

**Video Tool** là một công cụ tự động hóa **từ âm thanh → YouTube video**, tối ưu cho tốc độ xuất bản (**speed-to-publish**) thay vì chất lượng hình ảnh. Sản phẩm là **audio + nhạc nền + thumbnail**; visual chỉ tồn tại để vượt qua phát hiện YouTube static-frame penalty — không cần đẹp.

**Lợi ích:** Một creator audio-story có thể xuất 1 video trong ~1 giờ (thật) mà không cần kỹ năng chỉnh sửa video hay công cụ ngoài (CapCut, Premiere, v.v.).

---

## Target User

**Kênh YouTube dịch truyện âm thanh** (audio-first, không kể truyện bằng video):
- Bình Thiên Sách, Đạo Sĩ, Cuộc Sống Đầy Lạ Kỳ, v.v.
- ~1–2 tập/tuần, mỗi tập 30–120 phút
- Prioritize: xuất nhanh, theo kịp lịch trình
- Secondary: hiệu ứng ngoạn mục (mood FX, parallax), không bắt buộc

---

## Key Flows

### Flow 1: Light Job (Default)
```
voice.wav + media/ + music/ 
  → init-job → storyboard auto → validate → render (no re-encode) → package
  → youtube-16x9.mp4 (~1h real-time for 1h audio)
```

Không thêm subtitle (YouTube auto-CC đủ). Ken Burns motion vượt qua static detection.

### Flow 2: Full Job (With FX)
```
voice.wav + media/ + music/ 
  → init-job → storyboard auto → validate 
  → transcribe (whisper → chapters.json + captions.srt)
  → render --enhance full (single re-encode + mood + atmosphere + subtitle)
  → package
  → youtube-16x9.mp4 (~2–3h for 1h audio)
```

Gồm mood presets (5 loại) + atmosphere overlays (mưa/tuyết/lửa/etc.) từ CC0 library.

### Flow 3: Parallax Video (2.5D Stills)
```
voice.wav + media/ + music/ + Parallax/ (GPU-generated clips)
  → /parallax-video command (full auto)
  → parallax-link (swap stills with depth-clips at data layer)
  → render → package
  → youtube-16x9.mp4 (stills animate as 3D parallax)
```

Colab GPU offload: `v4_depthflow_clips_colab.py` → tải `Parallax/` clips → local render (no GPU needed).

---

## Success Criteria

### Speed Benchmarks

| Config | Duration | Target | Status |
|--------|----------|--------|--------|
| Light job (1h audio, 20 stills) | 1h real-time | <1.2h | ✓ Verified |
| Full job (1h audio, 20 stills, mood+atmosphere) | 2–3h real-time | <3.5h | ✓ Verified |
| Parallax job (Colab-offload, 1h audio) | Colab 4–6h + local 30min | <8h total | ✓ Verified |
| Transcribe (1h audio, Whisper base) | ~1 min | <2 min | ✓ Verified |
| Render Shorts (9:16, 1h audio) | 2h real-time (parallel to 16:9) | <4h total | ✓ Verified |

### Quality Metrics

- **Codec:** H.264 (libx264), AAC audio, 1920×1080 (16:9) or 1080×1920 (9:16)
- **Loudness:** −14 LUFS ± 1 LUFS (YouTube spec)
- **Motion:** Ken Burns amplitude 0.30, pan zoom 1.22 (prevents static detection)
- **Subtitle timing:** ±100ms of character position (interpolated from whisper span)
- **Chapter accuracy:** ±1s of "Chương" marker in transcript

### Feature Completeness

- [x] Tier light: no re-encode, Ken Burns
- [x] Tier full: single re-encode, mood + atmosphere + subtitles
- [x] Transcribe: offline whisper (base model, 1.5GB cached)
- [x] Chapters: auto-derived from "Chương" markers in aligned transcript
- [x] B-roll interleave: video clips spread by story order, full duration kept
- [x] Intro/ending images: both overlay narration (0–10s, last 10s), no added time
- [x] Sidechain audio: music auto-ducks under voice (ratio 8:1)
- [x] Parallax local (optional, CPU DepthAnything V2)
- [x] Parallax Colab (optional, GPU DepthFlow offload)
- [x] Shorts (9:16, opt-in only)
- [x] Mood FX (5 presets: clean/melancholy/cozy/horror/action)
- [x] Atmosphere overlays (CC0 library, durable `~/.local/share/videotool/overlays/`)
- [x] SFX insertion (validated 2026-06-24, char-position interpolation)
- [x] Progress bar (removed, viewer-side Sweezy-style, no-op key)

---

## Non-Goals

- **Cloud rendering:** All compute is local (CPU/GPU optional for parallax).
- **Social upload:** No direct YouTube/TikTok API integration (manual paste description).
- **CapCut compatibility:** No `.plist` export or CapCut timeline import.
- **Auto media fetch:** No semantic B-roll retrieval, Unsplash API, etc.
- **Full timeline editor:** No Premiere-style scrubbing UI; jobs are `job.yaml`-centric.
- **Auto model downloads:** All AI models (Whisper base, DepthAnything) are manually cached or offloaded.

---

## Confirmed Decisions (Do NOT Silently Reverse)

### Audio & Loudness
- **Loudness target:** −14 LUFS (YouTube spec), single-pass `loudnorm`, ±1 LUFS drift acceptable.
- **Music bed default:** −30 dB (user-adjustable); sidechain duck active (ratio 8:1, automatic under voice).
- **Audio-story channel override:** −30 dB default, `enhance.subtitles: true` forces caption burn.
- *(Decided 2026-05-31 / 2026-06-15)*

### Motion & Visual
- **Ken Burns amplitude:** 0.30, pan zoom 1.22 (bumped from 0.12 because long images need visible per-second motion).
- **Intro & ending images:** Both overlay narration (no added time) — intro 0–10s, ending last 10s. Keeps ending card flush with voice end so spliced outro CTA card stays in sync. *(Decided 2026-06-13)*
- **B-roll interleave:** Spread by story order, full duration kept, never drop. *(Decided 2026-06-13)*

### Tiers & Effects
- **Tier light:** No re-encode, no waveform, no subtitles. Zoompan defeats static detection. YouTube auto-CC suffices. Default for generic light jobs. *(Decided 2026-05-28)*
- **Tier full:** Single re-encode, burns subtitles, adds mood + optional atmosphere. *(Decided 2026-05-31)*
- **Mood FX (Group A):** Filter-only, free, no assets. 5 presets: clean/melancholy/cozy/horror/action. Independent of tier (tier=full alone does NOT enable it). Rides single full-tier re-encode. *(Decided 2026-06-15)*
- **Atmosphere overlays:** CC0 library at `~/.local/share/videotool/overlays/` (durable XDG data dir, NOT cache). One slot per video; `particles` wins if both enabled. Blending in `gbrp` (RGB), NOT yuv420p (magenta tint). *(Decided 2026-06-18)*
- **Progress bar:** Removed from every job (no-op key for legacy). Sweezy-style is viewer-side. *(Decided 2026-06-15)*

### Parallax & Offload
- **Parallax local:** Opt-in via `enhance.parallax: true` (independent of tier). Offline CPU DepthAnything V2 + numpy inverse-warp. Falls back to Ken Burns if depth fails. *(Decided 2026-06-15)*
- **Parallax Colab:** Separate `/parallax-video` command (NOT `enhance.parallax`). GPU offload path. Render reuses existing loop+trim — no torch required locally. Distinct from local-numpy. *(Decided 2026-06-18)*

### Render & Encoding
- **No auto Shorts:** Default render is `youtube-16x9` only; add `shorts-9x16` solely when user asks. `init-job` seeds single long-form preset. *(Decided 2026-05-29)*
- **Caption mode default:** `off` (not `srt-only`) for light jobs. `enhance.subtitles: true` forces burn via `transcribe` + full-tier. *(Decided 2026-06-15)*
- **No CapCut:** Tool is self-sufficient via FFmpeg. *(Decided 2026-05-28)*

### Subtitle & Chapters
- **Subtitle timing:** Script-aligned via char-position interpolation onto whisper timing, NOT segment-start (not flaky). *(Validated 2026-06-24, SFX insertion)*
- **Chapters:** Transcribe derives timestamps from "Chương" markers (≥3); hand-write if <3 (e.g., add "Giới thiệu"). *(Decided 2026-05-31)*

### Validation Pitfalls
- **particle_overlay must be inside job folder** (validation escapes); relative path from `$JOB_DIR`. *(Discovered 2026-06-21)*
- **<3 Chương → no chapters.json**, hand-write it. *(Discovered 2026-06-21)*
- **mood=horror glow washes out fireflies overlay** → next time glow:false when atmosphere on. *(Discovered 2026-06-21)*

---

## Dependencies & Constraints

| Dependency | Version | Why |
|------------|---------|-----|
| Python | 3.12+ | venv @ `.venv/` |
| Pydantic | 2.7+ | job_spec.py schema |
| FFmpeg | 6.1+ | libx264, AAC, filters |
| Faster-Whisper | (ai extra) | STT, optional |
| PyTorch | (parallax extra) | DepthAnything V2, optional |
| Numpy | (parallax extra) | Inverse-warp parallax, optional |

**Disk space:**
- Base: ~500MB (venv + code)
- Whisper model: ~1.5GB (cached at `~/.cache/videotool/models/`)
- Overlay library: ~5GB (durable at `~/.local/share/videotool/overlays/`)
- Temp per job: ~2× output size (inputs staged locally, deleted after)

---

## Implementation Roadmap

### Shipped
- ✓ V1 foundation (2026-05-20)
- ✓ Storyboard auto + B-roll (2026-05-29)
- ✓ Tier full + mood FX (2026-05-31)
- ✓ Chapters + description template (2026-05-31)
- ✓ Colab DepthFlow parallax (2026-06-18)
- ✓ Local DepthAnything parallax (2026-06-14)
- ✓ Atmosphere overlays + generators (2026-06-21)
- ✓ SFX insertion (validated 2026-06-24)

### Backlog (Deferred)
- Semantic B-roll retrieval (API-based asset fetch)
- Cloud rendering (serverless FFmpeg)
- Real-time GUI preview (async render watcher)
- CapCut timeline export
- Direct YouTube upload (API token management)

---

## Contact & Governance

- **Owner:** pndmmo@gmail.com
- **Git branch:** feat/parallax-2-5d (active)
- **Release cycle:** Feature-driven (no fixed cadence)
- **Decision log:** This file (PDR) + CLAUDE.md (workflow)

---

## Key References

- **[CLAUDE.md](../CLAUDE.md)** — Canonical workflow (do NOT invent new workflow)
- **[docs/system-architecture.md](./system-architecture.md)** — Render flow, audio chain, tier paths
- **[docs/deployment-guide.md](./deployment-guide.md)** — Setup variants, troubleshooting
- **[docs/code-standards.md](./code-standards.md)** — Python style, schema-first, testing
- **[docs/design-guidelines.md](./design-guidelines.md)** — Motion, loudness, subtitle timing, mood map
