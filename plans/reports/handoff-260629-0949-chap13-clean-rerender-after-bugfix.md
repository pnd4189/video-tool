# HANDOFF — Render lại Chap 13 (Bình Thiên Sách T13) sạch sau khi vá 3 bug

**Cho:** LLM/agent thực thi trên CHÍNH máy này (`/home/dung/VIBE_CODING/video-tool`, gdrive rclone mount + remote `gdrive:` đã có).
**Mục tiêu:** render lại 1 video duy nhất `youtube-16x9.mp4` cho Chap 13 ĐẦY ĐỦ (không cụt đuôi), sub khớp, CTA động đầu/cuối, SFX, description chuẩn template — rồi upload về `gdrive:.../Chap 13/Output/`.
**Vì sao handoff:** quota phiên gốc sắp cạn, không đủ duy trì ~90 phút render.

---

## 0. Bối cảnh: 3 bug đã vá (CODE đã ở working tree, CHƯA commit)

Lần render trước hỏng 3 chỗ, đã sửa trong source (uncommitted). **TUYỆT ĐỐI KHÔNG** `git checkout`/`reset`/`stash` các file dưới đây — sẽ mất fix:
- `src/videotool/render/executor.py` — bug #1: render scene ra `.part` rồi rename khi xong (atomic). Render bị kill giữa chừng KHÔNG còn để lại clip cụt bị resume tin nhầm.
- `src/videotool/core/services.py` — bug #2: `transcribe` ghi caption/chapter RAW; `_stage_subtitle` shift burn-copy theo intro CTA; `run_package` offset chapter + thêm "Giới thiệu". bug #3: `_stage_voice_cta` tự dùng clip `Intro/Outro CTA.mp4` làm visual khi không có `*_cta_image`.
- tests: `tests/test_cta_wiring.py` (mới), `tests/test_segmented_render.py`, `tests/test_description_template.py`.

**Verify trước khi làm bất cứ gì:**
```bash
cd /home/dung/VIBE_CODING/video-tool
.venv/bin/python -m pytest -q        # PHẢI thấy: 163 passed
```
Nếu không phải 163 passed → DỪNG, báo người dùng (fix đã bị mất/hỏng).

## Bất biến quan trọng (đọc kỹ, đây là gốc của lần hỏng trước)
1. **`chapters.json` phải là RAW** (Chương 121 ở `0.0`, KHÔNG có "Giới thiệu"). Bản trên gdrive `Output/chapters.json` đã bị shift tay +8.76 ở lần trước → nếu dùng sẽ bị offset **lần 2**. Bước 2 dưới đây GHI ĐÈ bằng bản RAW kèm sẵn.
2. **`captions.srt` trên gdrive đã RAW** (cue 0 ở `00:00:00,000`) — đúng. Code mới sẽ tự shift burn-copy +8.76 lúc render. KHÔNG shift tay.
3. **KHÔNG kill render giữa chừng.** Atomic clip đã chống resume-cụt, nhưng vẫn chạy nền + theo dõi tới khi xong, đừng timeout.
4. Render & encode chạy **local** (CPU Ryzen). KHÔNG đẩy lên Colab/Kaggle (filter CPU-bound, cloud chậm hơn — đã chốt).

---

## 1. Stage assets từ gdrive về cache local (nhanh, qua rclone)

```bash
cd /home/dung/VIBE_CODING/video-tool
SRC_REMOTE="gdrive:1. YOUTUBE AUDIO/BÌNH THIÊN SÁCH/BINH THIEN SACH - VO TOI/BẢN DỊCH/Chap 13"
TPL_REMOTE="gdrive:1. YOUTUBE AUDIO/BÌNH THIÊN SÁCH/BINH THIEN SACH - VO TOI/template/_DESCRIPTION_TEMPLATE.txt"
STAGE="$HOME/.cache/videotool/Chap13"

rm -rf "$STAGE" && mkdir -p "$STAGE/outputs" "$STAGE/overlays" "$STAGE/media"
# Assets (bỏ Output/ kết quả cũ). ~2-3 phút, ~360MB ảnh.
rclone copy "$SRC_REMOTE" "$STAGE" --exclude "Output/**" --transfers 8
# captions.srt RAW từ Output cũ (đã xác nhận raw)
rclone copyto "$SRC_REMOTE/Output/captions.srt" "$STAGE/outputs/captions.srt"
# description template + overlay (smoke phù hợp chiến trường C121-130)
rclone copyto "$TPL_REMOTE" "$STAGE/_DESCRIPTION_TEMPLATE.txt"
cp ~/.local/share/videotool/overlays/smoke-ffc-01.mp4 "$STAGE/overlays/"
ls "$STAGE"        # kỳ vọng: Image/ Video/ Music/ "CTA voice"/ "Ảnh bìa..."/ "Ảnh end video"/ mp3 + txt
```

## 2. Ghi RAW chapters.json (GHI ĐÈ, đừng shift tay)

```bash
cat > "$STAGE/outputs/chapters.json" <<'JSON'
[
  {"start": 0.0, "title": "Chương 121: Tướng lĩnh bên bờ nước trong."},
  {"start": 555.5901051392378, "title": "Chương 122: Chiến trường đồng quy vu tận."},
  {"start": 1174.6475635300803, "title": "Chương 123: Sự tương phản."},
  {"start": 1835.5325688073408, "title": "Chương 124: Di vật."},
  {"start": 2477.8489291223486, "title": "Chương 125: Xanh đỏ."},
  {"start": 3065.6902585856938, "title": "Chương 126: Tiến cảnh khủng bố."},
  {"start": 3685.210037346756, "title": "Chương 127: Chiến trường hỗn loạn."},
  {"start": 4221.109949257127, "title": "Chương 128: Cướp của."},
  {"start": 4869.819663879187, "title": "Chương 129: Sát tràng."},
  {"start": 5470.052155557354, "title": "Chương 130: Man đấu."}
]
JSON
```

## 3. Ghi job.yaml (full FX, overlay smoke, mood action; CTA mp4 tự thành visual nhờ bug #3)

```bash
cat > "$STAGE/job.yaml" <<'YAML'
version: 1
project:
  title: Bình Thiên Sách - Tập 13 | Chương 121-130
  language: vi
  recap_previous: "Lâm Ý cùng Thiết Sách Quân tiếp tục dấn sâu vào vùng biên ải mưa mù, chật vật truy tìm và truyền đạt quân tình giữa vòng vây Bắc Man. Một đứa con gái tư sinh xuất hiện, những cái bẫy được giăng ra, kẻ địch ngang sức dần lộ diện. Qua các chương Mồi, Túc địch, Đường lui — từng nước cờ sinh tử được tính toán, thân phận thật sự hé mở trước khi đoàn quân tìm được nơi đóng quân."
  description: "Nhận lệnh từ Hứa tướng quân, Lâm Ý một mình xâm nhập vùng Địa Tiên Ông đang tranh chấp dữ dội giữa Nam Lương và Bắc Ngụy. Giữa chiến trường hỗn loạn và đồng quy vu tận, hắn đối mặt với di vật bí ẩn, chứng kiến sự tương phản giữa hai thế lực, rồi vươn tới tiến cảnh khủng bố trong một trận sát tràng đẫm máu. Từ cướp của, man đấu đến biên giới sinh tử — mỗi bước Lâm Ý đi là một đánh cược với tính mạng giữa khói lửa Mi Sơn."
inputs:
  voice: Binh_Thien_Sach_0121_0130_vi_qa.mp3
  media_dir: media
  script: Binh_Thien_Sach_0121_0130_vi_qa.txt
  music: Music
  intro_image: "Ảnh bìa Thumbnail-Intro/Thumbnail - Binh thien sach (3).jpg"
  ending_image: "Ảnh end video/binh-thien-sach-ending-youtube.jpg"
  intro_cta: "CTA voice/Intro CTA - with voice.mp4"
  outro_cta: "CTA voice/Outro CTA - with voice.mp4"
  particle_overlay: overlays/smoke-ffc-01.mp4
  description_template: _DESCRIPTION_TEMPLATE.txt
outputs:
- preset: youtube-16x9
captions:
  mode: 'off'
assets:
  policy: allow-missing-local
render:
  encoder: libx264-balanced
  temp_dir: .videotool/tmp
enhance:
  visualizer: true
  subtitles: true
  mood: action
  atmosphere: true
  grain: false
  glow: false
YAML
```

> Lưu ý: KHÔNG set `intro_cta_image`/`outro_cta_image` → bug #3 đã sửa khiến tool tự dùng clip CTA `.mp4` (động) làm hình. Nếu muốn ảnh tĩnh thì mới set field đó.

## 4. Storyboard → validate → render (NỀN, theo dõi tới khi xong)

```bash
cd /home/dung/VIBE_CODING/video-tool
VT=.venv/bin/videotool
JOB="$HOME/.cache/videotool/Chap13/job.yaml"
STAGE="$HOME/.cache/videotool/Chap13"

$VT storyboard auto "$JOB" --images-dir "$STAGE/Image" --videos-dir "$STAGE/Video"
$VT validate "$JOB"          # kỳ vọng: OK job is valid

# Render NỀN — KHÔNG chạy foreground rồi để timeout kill (đó là lý do hỏng lần trước).
nohup $VT render "$JOB" --preset youtube-16x9 > "$STAGE/render.log" 2>&1 &
echo "render PID=$!"
```

Theo dõi tới khi xong (~90 phút; KHÔNG bỏ giữa chừng). Khi `youtube-16x9.mp4` ngừng tăng size và process biến mất là xong. Kiểm tra:
```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 "$STAGE/outputs/youtube-16x9.mp4"
```
**PHẢI ≈ 6147s (~6146.7s)**, KHÔNG phải ~6097s. Nếu vẫn ~6097s → đuôi vẫn cụt, DỪNG và báo (fix #1 không ăn). Mốc đối chiếu: audio = intro CTA 8.76 + narration 6123.29 + outro CTA 14.69 = 6146.74s.

## 5. Package (description tự offset chapter + thêm "Giới thiệu" nhờ bug #2)

```bash
$VT package "$JOB"
# Thêm "Tập 13" vào dòng tiêu đề description (cosmetic, template để generic)
sed -i '1 s/| Truyện Tiên Hiệp Audio/- Tập 13 | Chương 121-130 | Truyện Tiên Hiệp Audio/' \
  "$STAGE/outputs/description.txt"
```
Kiểm tra `description.txt`: phải có `00:00 Giới thiệu`, `00:08 Chương 121...`, `09:24 Chương 122...` (đã +8.76s). KHÔNG được thấy `00:00 Chương 121` (đó là chưa offset).

## 6. Chèn SFX (post-process, chỉ re-encode audio, ~6 phút)

Ghi script rồi chạy nền:
```bash
cat > "$STAGE/apply_sfx.sh" <<'BASH'
#!/usr/bin/env bash
# 20 cue SFX cho C121-130. Mốc = (raw_chapter_start + 8.76 intro CTA)*1000 ms.
# Mức: transient one-shot -17dBFS; loop/ambient -24 + highpass; bed -30 + highpass.
set -e
STAGE="$HOME/.cache/videotool/Chap13"
SFX="$HOME/.local/share/videotool/sfx/binh-thien"
INPUT="$STAGE/outputs/youtube-16x9.mp4"
OUTPUT="$STAGE/outputs/youtube-16x9-sfx.mp4"
declare -a CUES=(
  "$SFX/freesound_community-war-drum-loop-103870.mp3|8760|-30|highpass=f=150"
  "$SFX/freesound_community-marching-loop-32908.mp3|30000|-30|highpass=f=150"
  "$SFX/universfield-impact-cinematic-boom-352465.mp3|564350|-17|anull"
  "$SFX/freesound_community-war-drum-loop-103870.mp3|566000|-30|highpass=f=150"
  "$SFX/dragon-studio-horse-galloping-339737.mp3|610000|-24|highpass=f=200"
  "$SFX/daviddumaisaudio-sword-slash-and-swing-185432.mp3|700000|-17|anull"
  "$SFX/freesound_community-hit-swing-sword-small-2-95566.mp3|800000|-17|anull"
  "$SFX/dragon-studio-sword-unsheathing-393851.mp3|900000|-17|anull"
  "$SFX/universfield-cinematic-impact-hit-352702.mp3|1183410|-17|anull"
  "$SFX/universfield-impact-cinematic-boom-352465.mp3|1844290|-17|anull"
  "$SFX/studiokolomna-whoosh-transitions-sfx-01-118227.mp3|1846000|-17|anull"
  "$SFX/freesound_community-war-drum-loop-103870.mp3|2486610|-30|highpass=f=150"
  "$SFX/daviddumaisaudio-sword-slash-and-swing-185432.mp3|2490000|-17|anull"
  "$SFX/universfield-impact-cinematic-boom-352465.mp3|3074450|-17|anull"
  "$SFX/universfield-cinematic-impact-hit-352702.mp3|3076000|-17|anull"
  "$SFX/freesound_community-war-drum-loop-103870.mp3|3693970|-30|highpass=f=150"
  "$SFX/freesound_community-marching-loop-32908.mp3|3700000|-30|highpass=f=150"
  "$SFX/dragon-studio-sword-unsheathing-393851.mp3|4229870|-17|anull"
  "$SFX/universfield-impact-cinematic-boom-352465.mp3|4878580|-17|anull"
  "$SFX/freesound_community-war-drum-loop-103870.mp3|5478810|-30|highpass=f=150"
)
N=${#CUES[@]}
INPUTS=(-i "$INPUT"); FILTER_PARTS=(); AMIX="[0:a]"
for i in "${!CUES[@]}"; do
  IFS='|' read -r FILE DELAY VOL FILT <<< "${CUES[$i]}"
  INPUTS+=(-i "$FILE"); IDX=$((i+1)); L="[sfx${i}]"
  if [[ "$FILT" == "anull" ]]; then
    FILTER_PARTS+=("[${IDX}:a]volume=${VOL}dB,adelay=${DELAY}|${DELAY}${L}")
  else
    FILTER_PARTS+=("[${IDX}:a]volume=${VOL}dB,${FILT},adelay=${DELAY}|${DELAY}${L}")
  fi
  AMIX+="${L}"
done
CHAIN=$(IFS=';'; echo "${FILTER_PARTS[*]}")
CHAIN+=";${AMIX}amix=inputs=$((N+1)):duration=first:normalize=0[aout]"
ffmpeg -y "${INPUTS[@]}" -filter_complex "$CHAIN" \
  -map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 192k "$OUTPUT"
echo "SFX applied: $OUTPUT"
BASH
chmod +x "$STAGE/apply_sfx.sh"
nohup "$STAGE/apply_sfx.sh" > "$STAGE/sfx.log" 2>&1 &
echo "sfx PID=$!"
```
Chờ tới khi log in `SFX applied`. Rồi thay bản gốc:
```bash
ffprobe -v error -show_entries format=duration -of csv=p=0 "$STAGE/outputs/youtube-16x9-sfx.mp4"  # ≈6147s
mv "$STAGE/outputs/youtube-16x9-sfx.mp4" "$STAGE/outputs/youtube-16x9.mp4"
```

## 7. Upload về gdrive + dọn cache

```bash
DEST="gdrive:1. YOUTUBE AUDIO/BÌNH THIÊN SÁCH/BINH THIEN SACH - VO TOI/BẢN DỊCH/Chap 13/Output"
rclone copy "$STAGE/outputs/" "$DEST" --transfers 4    # ~15 phút cho ~5GB
rclone ls "$DEST"          # xác nhận youtube-16x9.mp4 + description.txt + thumbnail* + chapters.json + captions.srt
rm -rf "$STAGE"            # CHỈ xóa cache local; KHÔNG đụng gì dưới mount/remote
```

---

## Tiêu chí nghiệm thu (kiểm đủ trước khi báo xong)
- [ ] `pytest -q` = 163 passed trước khi render.
- [ ] `youtube-16x9.mp4` duration ≈ **6146-6147s** (KHÔNG ~6097s) → đuôi truyện đủ, nghe được câu cuối "...chiến ý trong mắt dạt dào" + outro CTA.
- [ ] Sub khớp giọng (không sớm 8.76s): chữ "Chương 121" xuất hiện ~00:08 (sau intro CTA), không phải 00:00.
- [ ] Đầu video là clip **Intro CTA động** (không phải ảnh tĩnh), cuối là **Outro CTA động**.
- [ ] `description.txt` có `00:00 Giới thiệu` + `00:08 Chương 121...` (đã offset) + recap + summary, đủ template không vắn tắt.
- [ ] SFX nghe rõ ở các mốc chiến đấu, không át giọng.
- [ ] Đã upload `Output/`, đã `rm -rf "$STAGE"`.

## Rủi ro / chưa giải quyết
- File ~5GB (overlay smoke + showwaves đẩy CRF20 ≈ 7Mbps). Đây là chủ ý (full FX). Muốn nhẹ hơn: thêm `-maxrate 3M -bufsize 6M` hoặc nâng CRF — KHÔNG nằm trong phạm vi lần này, hỏi người dùng trước.
- Fixes đang UNCOMMITTED. Sau khi render OK, hỏi người dùng có muốn commit (conventional, không ref AI) không.
- `chapters.json` trên gdrive Output (bản shift tay cũ) sẽ bị bản RAW mới ghi đè khi upload — đúng ý đồ (RAW là canonical, description mới offset trong code).
