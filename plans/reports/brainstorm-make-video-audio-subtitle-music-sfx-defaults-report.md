# Brainstorm — /make-video default overhaul: SRT-sub, SFX, music-schedule, audio/sub quality

Date: 2026-07-03 22:48 | Branch: main | Status: design approved (defaults confirmed), pending /ck:plan

## Problem / requirements (user, 7 items)

1. Bỏ whisper tạo sub khỏi flow mặc định `/make-video`; dùng SRT người dùng cung cấp.
2. Mặc định KHÔNG bật mood overlay.
3. Mặc định có SFX mức vừa, timing khớp, âm thanh hợp bối cảnh hành động.
4. Music đặt đúng đoạn: mood/tả cảnh → nhạc nhẹ, hành động → nhạc tiết tấu nhanh; căn theo file music-prompt trong folder.
5. Render bằng WAV (chất lượng + khớp sub mux), không MP3.
6. Sub màu vàng (dễ đọc → giữ chân → gián tiếp tốt ranking; KHÔNG phải thuật toán đọc màu). Chỉ áp cho audio-story.
7. Audio render chất lượng tối ưu, dễ nghe.

## Scout — hiện trạng code

- Whisper: `services.py:240 run_transcribe` → `outputs/captions.srt` + `chapters.json` (chapters TỪ transcript). Burn phụ thuộc `enhance.subtitles` + captions.srt tồn tại.
- Mood: đã opt-in sẵn (`job_spec.py:152,160` default off). "Chặn" nằm ở bước đề xuất trong CLAUDE.md, không phải code.
- SFX: CHƯA phải feature — chỉ post-process thủ công (memory `sfx-insertion-workflow`). Thư viện `~/.local/share/videotool/sfx/{binh-thien,dao-si}`; asset type `sfx` đã có trong schema.
- Music: một bed liên tục — concat tất cả track (natural-sort) + loop (`services.py:_resolve_music_tracks` + `music_loop.prepare_seamless_music`). Không có khái niệm đặt theo đoạn.
- Voice/WAV: render lấy `job.inputs.voice` bất kỳ; audio luôn re-encode AAC 192k. Chưa có ưu tiên wav.
- Sub style: `overlay_graph.py:136 caption_filter` — force_style KHÔNG set màu → libass trắng, Outline=3 Shadow=1 Alignment=2.
- Audio: AAC 192k/48k/stereo, `loudnorm I=-14:TP=-1:LRA=11` ở 3 chỗ (`commands.py:79,139`, `segmented.py:120`).

## Music-prompt format (xác nhận từ Chap 13)

`*_vi_music_prompts.txt` = N khối prompt theo thứ tự (Chap13 = 4), mỗi khối = đoạn mô tả mood/nhạc cụ + dòng `Tags:`. **Khối i ↔ track i** trong `Music/` (natural-sort). 4 track = vòng cung cảm xúc: tĩnh-trước-bão → u ám rừng sâu → bi thương hậu chiến → hào hùng chiến thắng. Map theo mood-arc.

Phát hiện: folder chỉ có `_vi_qa.mp3` (không wav) → #5 phải "ưu tiên wav, fallback mp3", không cứng. Chưa có `.srt` (user cấp sau).

## Kiến trúc chốt: LLM là bộ phân loại, tool chỉ render cue

Giữ đúng pattern hiện có (mood/overlay). `/make-video` (LLM) đọc truyện + prompt, ghi cue vào `job.yaml`; tool render theo cue. Không nhét AI vào code.

## Quyết định (đã chốt với user)

- Music: lịch theo thời gian; timing từ timecode SRT (LLM khớp câu chuyển-mood ↔ cue), marker "Chương" là shortcut nếu có, fallback chia đều nếu không có SRT.
- SFX: mặc định BẬT, mức vừa (~12–20 cue/45ph, scale theo độ dài), **auto-burn, KHÔNG montage**. Precision = keyword + nội suy ký tự (không tin whisper segment-start).
- Palette SFX: LLM tự nhận theo thể loại truyện.
- Sub vàng #FFFF00 + viền đen: CHỈ audio-story (field cấu hình, default trắng).
- Audio: AAC 256k, giữ loudnorm −14 LUFS.
- Chia 2 plan.

## PLAN 1 — Quick-wins (rủi ro thấp)

| # | Việc | Chỗ sửa |
|---|---|---|
| 1 | Bỏ whisper khỏi flow mặc định | CLAUDE.md + skill: bỏ bước transcribe; cp SRT user → outputs/captions.srt; chapters từ marker/SRT. `run_transcribe` GIỮ (còn dùng cloud GPU). |
| 2 | Mặc định không mood | CLAUDE.md: bỏ bước đề xuất mood. Không sửa code. |
| 5 | Ưu tiên wav, fallback mp3 | Skill auto-detect voice. Không bắt buộc cứng. |
| 6 | Sub vàng (chỉ audio-story) | Thêm `enhance.subtitle_color` (default trắng); `overlay_graph.py:136` đọc → PrimaryColour + OutlineColour đen. Skill seed vàng cho audio-story. |
| 7 | Audio 256k | `commands.py:79,139` + `segmented.py:120`: 192k→256k. Giữ loudnorm −14 LUFS. |

## PLAN 2 — Feature

**#4 Music theo đoạn:**
- Schema: `audio.music_schedule: [{track, start, end, gain_db?}]` (optional; vắng → concat-loop cũ, backward-compat).
- `/make-video`: đọc `_vi_qa.txt` + N prompt (khối i↔track i) → gán track vào khoảng mood → giây từ timecode SRT → ghi schedule.
- Render (`audio_graph.py`+`music_loop.py`): mỗi track loop-đầy-cửa-sổ + crossfade ranh giới.

**#3 SFX mức vừa (auto-burn):**
- Schema: `enhance.sfx: {enabled, pack?, cues:[{time,file,gain_db}], beds?}`.
- `/make-video`: scan SRT keyword hành động (lọc đồng âm ẩn dụ) → pin nội suy ký tự → chọn file từ `sfx/<palette>` → normalize per-cue → ghi cues (auto, no montage).
- Render: mix trong `audio_graph.py`; SFX KHÔNG duck; `amix normalize=0` + `alimiter`.

## Approaches đã cân nhắc & loại

- Music: "giữ concat chỉ sắp thứ tự" (loại — không bám đoạn); "lịch theo scene" (loại — quá mịn, nhiều crossfade). Chọn "lịch theo thời gian từ SRT".
- SFX timing: whisper word_timestamps re-transcribe (loại — flaky vi base, 3/10 khớp) → chọn nội suy ký tự deterministic.
- Sub vàng: hardcode global (loại — user chỉ muốn audio-story) → field cấu hình.

## Rủi ro

- SFX auto-burn không montage: 1 cue lệch/sai bối cảnh = phản cảm, phát hiện sau. Giảm thiểu = keyword precision + nội suy + lọc đồng âm (đã chạy ở T12).
- Music schedule khi SRT thiếu timecode/marker: fallback chia đều kém bám đoạn.
- Sub color field mới: cần backward-compat với job.yaml cũ (default trắng, `extra=forbid` OK vì thêm field có default).
- Audio 256k ở 3 chỗ: sửa đủ 3, tránh lệch giữa inline/segmented.

## Success metrics

- `/make-video` chạy end-to-end KHÔNG transcribe; SRT user → sub burned + chapters.
- Nhạc đổi track đúng mốc mood (nghe thử ranh giới crossfade sạch).
- SFX rơi đúng từ hành động (sai số < ~0.3s), không đè exposition.
- ffprobe: aac 256k; sub audio-story hiển thị vàng viền đen.
- Test suite ≥ 66 passing.

## Open questions

1. SRT user cấp có luôn kèm timecode chuẩn? (giả định có — SRT luôn có timecode; marker chương optional).
2. `enhance.sfx.beds` (nhạc nền trận đánh) có làm ngay ở Plan 2 hay để sau? (đề xuất: point-cues trước, beds sau).
3. Mức "vừa" cho SFX: cố định ~12–20/45ph hay có cờ chỉnh mật độ? (đề xuất: default vừa, có thể chỉnh qua hint).
