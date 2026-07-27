# Brainstorm: Full render pipeline trên Colab/Kaggle + LLM orchestrator

Date: 2026-07-07 · Status: AGREED · Reverses prior decision "render stays local" (2026-06, user-driven)

## Problem

`/make-video` render (libx264, 45-90min video) chiếm CPU local hàng giờ, máy nóng, không làm việc khác được. Pain = nhiệt/độ bền + máy bị chiếm dụng (KHÔNG phải tốc độ). Muốn offload toàn bộ — kể cả phần LLM-authoring — lên Colab/Kaggle free tier.

## Key facts (scouted)

- `Colab/v1_current_workflow_colab.py` đã chạy full 4-step pipeline trên Colab (Gradio, pre-overhaul-2026-07-03, thiếu SRT-flow/music_schedule/SFX/CTA).
- `gdrive:_VIDEOTOOL_SHARED/videotool_cloud.py`: setup + wheelhouse + model cache, validated cho whisper.
- `render/profiles.py` chỉ wire libx264 (CPU-only). Colab 2 vCPU / Kaggle 4 vCPU < local CPU → cloud CPU-encode CHẬM HƠN local. NVENC (T4) là bắt buộc để cloud có lợi tốc độ. P100 Kaggle KHÔNG có NVENC — chọn T4.
- Assets đã nằm trên Drive → không tốn upload; output ghi về `Output/`.
- LLM-authored steps (music_schedule, SFX cues, description/recap, chapters, mood) = structured generation, có pydantic schema validate + retry được → offload cho LLM API rẻ khả thi.

## Evaluated approaches

| # | Approach | Verdict |
|---|---|---|
| A | Hybrid: local author, cloud render | Ổn nhưng vẫn cần local mỗi tập |
| B | Full-cloud Gradio, heuristic thay LLM | Rejected — mất chất lượng SFX/description |
| C | Giữ local, tối ưu tại chỗ | Rejected — không giải quyết pain |
| **D** | **Full-cloud + LLM orchestrator trong notebook** | **CHỌN** |

Kaggle bundled models (Gemma/Llama local trên T4): rejected — tiếng Việt kém cho lọc đồng âm SFX, chiếm VRAM, chậm khởi động. API call thắng.

## Agreed design (D)

```
Drive asset folder → Colab/Kaggle notebook (1 cell)
 1. videotool_cloud.setup()                      # có sẵn
 2. cloud_director.py (MỚI) — LLM provider pluggable:
    Colab: GLM coding plan (Anthropic-compatible endpoint Zhipu)
    Kaggle: configurable per-run (Gemini Flash / Claude Haiku / ...)
    Key từ Colab Secrets / Kaggle Secrets, KHÔNG vào repo/Drive
    → author job.yaml: music_schedule, sfx cues, description+recap,
      chapters fallback, mood (chỉ khi hint)
    → `videotool validate` + retry loop khi schema fail
 3. Nếu có Parallax/ (pre-rendered v4 DepthFlow, flow riêng như hiện tại)
    → `videotool parallax-link` (data-layer swap, không cần torch)
 4. render --preset youtube-16x9, profile MỚI h264_nvenc,
    segmented + checkpoint từng segment về Drive (resume sau disconnect)
 5. videotool sfx → package → Output/ trên Drive
```

Parallax GENERATION không thuộc scope — vẫn là bước riêng (v4 script) sinh `Parallax/` trước.

## Work items (phase 1)

1. `h264_nvenc` profile trong `render/profiles.py` + wire render/mux path (quality target ≈ libx264-balanced-capped, giữ size cap <2.5GB).
2. `cloud_director.py`: LLM provider abstraction (OpenAI/Anthropic/Gemini-compatible), prompt đóng gói 4 tác vụ authoring, schema-validate + retry, conservative SFX rules (ít cue, chỉ keyword rõ nghĩa).
3. Segmented render checkpoint → Drive (rsync segment dir mỗi N scene) + resume detect.
4. Runner notebook hợp nhất (nâng từ colab_runner.ipynb): Colab mount Drive native; Kaggle qua rclone token (đường phụ khi hết quota Colab).

## Risks / accepted trade-offs

- SFX/description do model rẻ viết < chất lượng Claude local → mitigate: rule bảo thủ + user duyệt description trước khi đăng.
- NVENC chất lượng nén < libx264 CRF cùng bitrate → chấp nhận (nội dung zoompan ít motion detail), user đã đồng ý.
- Free-tier disconnect thường xuyên → checkpoint Drive là BẮT BUỘC.
- GLM coding plan cho raw API call: cần verify quota/ToS khi implement.
- Kaggle không mount Drive native → rclone setup friction; Kaggle là secondary.

## Success criteria

- 1 tập audio-story render end-to-end trên Colab free: chỉ input = Drive folder path, output = mp4 + description + captions.youtube.srt trong `Output/`, KHÔNG chạm CPU local.
- Sau disconnect giữa render, chạy lại cell → resume, không mất segment đã encode.
- SFX cues pass ear-audit; description dùng được sau chỉnh nhẹ.
- Local pipeline (/make-video) không đổi hành vi — cloud là đường song song, không thay thế.

## Unresolved questions

- GLM coding plan ToS/quota cho non-coding-tool API call — verify ở phase implement.
- NVENC bitrate/quality target cụ thể (VBR maxrate nào để giữ <2.5GB) — đo thực nghiệm 1 đoạn mẫu.
- Kaggle rclone token flow — chỉ làm khi thật sự cần secondary path.
