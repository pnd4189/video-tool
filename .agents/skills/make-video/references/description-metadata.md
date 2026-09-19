# Title, description, chapters, metadata, captions

Sources: memories `series-channel-ownership`, `mp4-metadata-prefill`,
`binh-thien-description-template-recap`, `dao-si-cta-and-description-template`, `youtube-srt-sidecar`,
episode logs dao-si-chap23/30/32/36/38, chap37/38/41/50/51.

## Absolute rule: no Chinese

No CJK character anywhere in the description, the template, `project.*`, or the mp4 tags
(user 2026-08-25). Old templates still carry 平天策/无罪/轩辕小胖 — never trust a copied template.
Run `grep -P '[\x{4e00}-\x{9fff}]'` (or Python `re.search('[一-鿿]', s)`) on every file you
wrote or copied before staging. A hand-typed "热点" slipped in once (dao-si-chap30).

## Title (`project.title`)

- Copy the exact line for this tập from `title_source` in series.yaml. Never invent or edit it.
- `title_pipe_to_dash: true` → replace `|` with ` - ` (Windows rejects `|`; tag and filename then match).
- It becomes the mp4 filename via `videotool metadata` (`safe_filename` turns `:` into ` - ` and
  drops `>` `/`). YouTube prefills the upload title from the filename — the real benefit.
- Special cases the user decided per episode (e.g. " (Tập Cuối)") come from the user, not from you.

## Metadata (`project.metadata`)

Constant per series — copy `channel`, `channel_url`, `original_author`, `copyright` from
series.yaml; `subtitle: "Chương A-B"`; `release_date` = today (YYYY-MM-DD). Tags + Genre are read
back from the rendered `description.txt` (`==== TAGS` block, `• Thể loại:` line), so they match the
description automatically. Needs ExifTool (`~/.local/share/videotool/exiftool/exiftool`); on the
box the step is best-effort and never kills a finished render.

## Description template

- The box/local `package` reads a job-root `*_DESCRIPTION_TEMPLATE.txt` with the placeholders
  `{{SUMMARY}}`, `{{RECAP_PREV}}`, `{{CHAPTERS}}`. No placeholders or leftovers → warning.
- **Build the new template from the previous episode's RENDERED description** (keeps correct
  diacritics): take `Chap N-1/outputs/description.txt`, change the title line, hashtags and the
  episode tags, then put the three placeholders back where summary/recap/chapter list were.
  Do not hand-type long Vietnamese (dao-si-chap23 got "ngưới"/"đỜi").
- After any `sed`, `grep` the result: a pattern without diacritics ("binh thiên") silently matches
  nothing (chap37, chap38).
- Bình Thiên base = `Chap 41/outputs/description.txt` (user-edited 2026-08-27): Bối cảnh line without
  "Nam Lương, thành Kiến Khang -"; tag `bình thiên sách tập N` right after `lâm ý`, then
  `kiếm vương triều, thông thiên chi lộ`; no "Linh dị, Đô thị" genre; no "Video phi thương mại" bullet.
- ĐẠO SĨ base = the previous Chap's template/description; dòng 1 uses " - " not "|"; "đạo sĩ phế vật".
- The user sometimes edits a published description by hand afterwards (mtime newer than the mp4) —
  a diff against it does not mean your template is wrong.
- Limits: YouTube caps the description at 5000 chars — count the part BEFORE `==== TAGS`
  (DS37 was 4940). Tags counted YouTube-style (+2 per tag with a space) run ~560 > 500; the user
  trims them when pasting — just mention it. Avoid `<` `>` in text the user pastes.

## Summary and recap

- `project.description` → `{{SUMMARY}}`: about 3 sentences, spoiler-light, ends on a hook.
- `project.recap_previous` → `{{RECAP_PREV}}`: the previous tập's own `project.description`
  (its creative.yaml or its rendered SUMMARY paragraph). Do not re-summarize from scratch.
- Write them from `*_vi_qa.txt` of THIS episode; check names and numbers against the text
  (an earlier run garbled two facts — chap25).

## Chapters

- `project.chapters` in creative.yaml is the final word for `chapters.json` (narration seconds,
  `[{start, title}]`) on Kaggle. Locally `package` prefers an existing `outputs/chapters.json`
  over `job.yaml` `project.chapters`, so write the list into `outputs/chapters.json` yourself
  (SKILL.md Step 4b). `package` shifts by the intro CTA and prepends `00:00 Giới thiệu`.
- Take each start from the SRT cue that opens "Chương N:" (a stray leading quote is fine).
  Titles: short "Chương N: Tên" from the chapter heading in `*_vi_qa.txt` — SRT markers can be
  whole sentences (chap51). Keep the qa.txt punctuation (some tập have a trailing period).
- ĐẠO SĨ numbers chapters relative to the TTS batch ("Chương 1..4" or "30..34"). Read the real
  markers in the SRT, then add `captions: {renumber: {30: 109, 31: 110, …}}` so the BURNED subtitles,
  description and chapters.json all carry the absolute numbers (fix `06000ce`; before Chap 31 this
  needed post-render editing).
- ĐẠO SĨ adds ~1 sub-beat per chapter (a short hook title at a real moment). Keep a sub-beat
  ≥ ~30s away from a chapter marker (dao-si-chap28).
- Timestamps under 1h render without a zero-padded minute ("30:00") — match that style.
- Fewer than 3 "Chương" markers → `chapters-from-srt` writes nothing; `project.chapters` covers it.

## Captions

- The provided `*_vi_qa.srt` → `outputs/captions.srt` (RAW, narration-aligned; the burn baseline).
  `transcribe`/whisper only when no SRT exists.
- With an intro CTA, `package` also writes `captions.youtube.srt` shifted by the CTA length. The user
  uploads THAT one as the YouTube sidecar; its first cue starts at the CTA length (8,760 BT / 16,853 ĐS).
- Words like "Chương 13" inside subtitle lines are narration read aloud — leave them.
