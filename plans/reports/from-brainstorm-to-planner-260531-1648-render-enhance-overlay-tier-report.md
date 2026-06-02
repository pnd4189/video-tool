# Brainstorm: Render Enhance — Overlay Tier (YouTube anti-strike)

**Date:** 2026-05-31 16:48
**Mode:** brainstorm → /ck:plan --tdd
**Sources read:** Gemini report `gdrive/KHÁC/Linh tinh/phân tích tình hình Youtube VN.txt`; MKT report `MARKETING/MKT-research/research-report-youtube-truyen-audio-tien-hiep-vietnam-2025.md`

## Problem statement
User muốn nâng cấp tool render: SFX vũ khí/hành động, nhiều BGM, sóng nhạc, subtitle nhanh từ txt có sẵn, hiệu ứng mưa/gió/tuyết + chuyển động. Câu hỏi gốc: thêm effect có giúp hạn chế bị YouTube đánh gậy + tối ưu thuật toán không.

## Honest findings (brutal)
1. **Effect ≠ miễn nhiễm gậy.** YouTube đánh "reused/AI slop" theo 4 tín hiệu: (a) voice-AI footprint, (b) script không transformative, (c) upload velocity/interchangeability, (d) slideshow ảnh tĩnh "ngâm 37s". Particle/sub/visualizer **chỉ chữa (d) + editing-value**, KHÔNG chữa (a)(b) — vốn là sát thủ lớn hơn. Effect = cần nhưng không đủ.
2. **Thị trường gate ROI.** MKT: VN tiên hiệp 4.3/10, RPM $0.05–0.15. Gemini: pivot English (Stoicism/True Crime/Cosmic Horror/Romantasy) RPM $4–15. Overlay chỉ đáng đầu tư ở thị trường YPP-gắt + RPM cao.
3. **Overlay là combo chi phí.** Segmented mux đang `-c:v copy`; bất kỳ overlay phủ-toàn-thời-lượng nào (sub/particle/visualizer/progress bar) đều phá copy → re-encode ~2x. Làm cả gói 1 lượt hoặc không.

## Codebase context (đã có sẵn hạ tầng)
- `ai/align_script.py` — re-time txt→timing audio: ĐÃ code. `ai/faster_whisper_adapter.py`, `transcribe.py`, `subtitles.py` (SRT+burn): ĐÃ code. Chỉ thiếu: cài lại `faster-whisper` + wire + bật `captions.mode`.
- `core/services.py:160 run_caption`, `:214 _stage_subtitle`, `:231 _resolve_music_tracks` (concat+loop BGM đã có).
- `render/video_filters.py` ZOOM_AMPLITUDE=0.30 PAN_ZOOM=1.22 (chỉ zoompan, chưa particle).
- `render/segmented.py` mux `-c:v copy` (>40 scene).
- Quyết định cũ: no-whisper, no-waveform (2026-05-28, lý do render-time).

## Decisions (user-confirmed)
- **Thị trường:** CẢ HAI → kiến trúc `enhance.tier: light|full` flag trong job.yaml.
- **Sub từ txt:** BẬT LẠI Whisper (đảo no-whisper, *chỉ* tier full). Reuse align_script+faster_whisper. Timing-only nên VN accuracy đủ.
- **Re-encode:** CHẤP NHẬN ~2x segmented, làm cả gói 1 filter pass.
- **SFX impact (gươm/chưởng va chạm):** BỎ. Chi phí timing cao nhất, value thấp nhất, hại AVD audience nghe-ngủ. (Ambient mood-bed để phase sau nếu cần.)
- **Plan mode:** /ck:plan --tdd.

## Solution: overlay tier flag
- **tier=light (default = hiện trạng):** zoompan + concat-BGM + duck, mux `-c:v copy`. Zero regression, giữ 66+ test. Dùng cho VN.
- **tier=full (English):** segmented mux → re-encode, gói overlay 1 pass:
  1. Sub burn từ txt (whisper transcribe → align_script → burn) — value cao nhất.
  2. Particle/grain overlay (dust loop 60fps blend screen + noise/vignette nhẹ; asset trong repo).
  3. Progress/chapter bar (drawbox + drawtext).
  4. Audio visualizer (showwaves góc) — chỉ tier full, đảo no-waveform *có giới hạn*.

## Touchpoints
`core/job_spec.py` (block enhance) · `core/services.py` (wire caption+overlay khi full) · `render/segmented.py`+`render/video_filters.py` (overlay pass + mux re-encode điều kiện) · `ai/transcribe.py`/`faster_whisper_adapter.py` (cài dep) · `cli/main.py` (flag) · `CLAUDE.md` (ghi rõ no-whisper/no-waveform giờ chỉ áp tier light).

## Risks
- Segmented re-encode tier full ăn RAM/time lớn với 100+ ảnh → test 1 job thật trước khi chốt filter graph.
- Whisper chỉ cần đúng *timing* (text lấy từ txt thật) → accuracy risk thấp.
- **Quan trọng:** gói full KHÔNG thay thế xử lý voice-AI + script transformative (intro voice thật, biên tập kịch bản) — 2 rủi ro gậy lớn hơn nằm ngoài tool.

## Success criteria
- tier=light render output byte-tương đương hiện trạng (regression guard).
- tier=full: mp4 có sub burn khớp voice, particle layer, progress bar; ffprobe h264+aac đúng res.
- `videotool caption <job>` sinh SRT timing-aligned từ txt.
- Test suite vẫn pass (cũ + mới cho tier full).

## Unresolved
1. Particle asset: tự gen (ai-multimodal/Veo) hay tải free pack? → quyết ở plan.
2. Sub style: SRT plain burn (rẻ) hay ASS kinetic/karaoke word-highlight (Gemini rank #1, đắt hơn)? → quyết ở plan, ảnh hưởng phạm vi.
3. faster-whisper model size cho VN timing (tiny/base đủ?) → benchmark ở plan.
