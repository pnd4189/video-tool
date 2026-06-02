---
title: "Make-video real run — Chap 3 (chương 21-30) quality eval"
type: test-run-evaluation
date: 2026-06-01
job: "BÌNH THIÊN SÁCH / Chap 3 (chương 21-30), 93 phút"
status: success-with-findings
---

# Đánh giá run thật `/make-video` — Chap 3

## Kết quả: THÀNH CÔNG, đủ tính năng. Output ở `.../BẢN DỊCH/Chap 3/Output/` (2.0GB).

## 1. Chất lượng output (PASS hết quality gate)
- `youtube-16x9.mp4`: **h264 1920×1080, 5584.2s (=93:04, khớp đúng audio), aac 48kHz stereo, 2.0GB**.
- **LUFS −14.2** (target −14 ±1.5) → pass.
- **description.txt**: render template hoàn hảo — title Tập 3, recap tập trước + tóm tắt tập này + **10 mốc chương** đúng format YouTube (`00:00 … 01:24:41`), **0 placeholder sót**, tags giữ nguyên.
- **chapters.json**: 10 chương, mốc đầu 00:00, cách ~9 phút, hợp lý.
- **Phụ đề tiếng Việt burn rõ, đọc tốt** (đã soi frame).
- **showwaves CÓ render** (xác minh trong filtergraph + thấy đường sóng khi phóng dải đáy).
- **music bed −30dB** ✓ + ducking sidechain + loudnorm áp đúng.
- Đủ artifact: captions.srt, chapters.json, description.txt, 5 thumbnail, license/quality/manifest. quality-report 11/11 pass.

## 2. Tuân thủ workflow (ĐÚNG AGENTS.md)
- Stage gdrive→local (`~/.cache/videotool/Chap3`), không ghi mount khi xử lý ✓
- `allow-missing-local`, channel default `enhance{visualizer,subtitles, progress_bar:false}` ✓
- `inputs.script`=vi.txt, `inputs.description_template` ✓
- transcribe (whisper base) TRƯỚC render, sinh captions.srt + chapters.json ✓
- >40 scene → segmented path, mux re-encode (không `-c:v copy`) cho overlay ✓
- Publish về `Output/`, chỉ `rm -rf` staging local (4.5GB reclaimed) ✓

## 3. Thời gian (tham khảo, CPU libx264)
- transcribe 6′ · render 76′ (clip 150×≈10s = 24′ + **mux re-encode 52′**) · package 2′ → tổng **~84′ cho video 93′**.

## 4. Vấn đề / cần cải thiện

### 🔴 P1 — Doc bug: `transcribe --model base` FAIL
`--model` bị dùng làm PATH; `base` không phải path → "model path does not exist". Thư mục `~/.cache/videotool/models/faster-whisper-base` **rỗng** (ghi chú "offline sẵn" SAI). Đã tải `Systran/faster-whisper-base` (~145MB) về đúng path → giờ chạy được.
**Fix:** sửa AGENTS.md + make-video docs dùng `--model "$HOME/.cache/videotool/models/faster-whisper-base"` (không phải `base`); sửa câu "AI extras offline ready".

### 🟡 P2 — showwaves quá mờ, không ra "sóng nhạc"
`mode=line` = đường 1px `white@0.65` trên nền ảnh bận → gần như tàng hình ở kích thước xem thật. Không đạt mục đích thị giác.
**Đề xuất:** đổi `mode=cline`/`p2p`, tăng độ dày/biên độ, hoặc đặt trên dải nền bán trong suốt (drawbox tối phía sau). Cần quyết định layout.

### 🟡 P3 — Phụ đề to & cao hơn ý định, đè dải showwaves
Thiếu `PlayResX/Y` trong `force_style` → libass dùng canvas mặc định 384 → `FontSize=42`/`MarginV=64` bị scale ×2.8 → chữ to, nằm ~giữa-dưới (≈y866-1016), **chồng dải showwaves (y948+)**. (Khớp cảnh báo va chạm đã nêu lúc brainstorm.)
**Fix:** set `PlayResX=1920,PlayResY=1080` trong force_style (hoặc tính font/margin theo preset thật) để phụ đề hugging đáy đúng 64px và không đè sóng.

### 🟡 P4 — Title chương 24 dính câu thoại
`chapters.json` ch.24 = `Chương 24: Đọc nhiều sách một chút "Đây là Dịch Nhã Tử Châm sao?` — cue heading nuốt text kế (vi.txt chương đó có thể thiếu blank line). W1 lấy verbatim cue.
**Fix:** cắt title tại `"`/`.`/`!`/`?` hoặc giới hạn ~60 ký tự trong `derive_chapters`.

### 🟡 P5 — 150 scene từ 10 ảnh (lặp ×15)
Autogen fill đủ 93′ bằng cách lặp 10 ảnh → 150 clip encode + mux. Tốn encode + nhìn lặp đơn điệu.
**Đề xuất:** hoặc cảnh báo khi (#ảnh × maxScene) << thời lượng, hoặc cho phép ít scene dài hơn (giảm số clip = render nhanh hơn). Cân nhắc với user.

### 🟢 P6 — Template phải có placeholder
File `_DESCRIPTION_TEMPLATE.txt` gốc CHƯA có `{{CHAPTERS}}/{{RECAP_PREV}}/{{SUMMARY}}`. Run này tôi tạo bản tokenized ở STAGING (gdrive gốc chưa đổi). Muốn dùng tiếp phải cập nhật template thật 1 lần.

## Unresolved questions
- showwaves nâng cấp tới mức nào (mode/độ dày/nền) — cần ý kiến thẩm mỹ user.
- Có muốn giảm số scene (ít ảnh-lặp, render nhanh) hay giữ 150 clip để "động" hơn?
- Cập nhật template gốc trên gdrive luôn hay giữ thủ công mỗi tập?
