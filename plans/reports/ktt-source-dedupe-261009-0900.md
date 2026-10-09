# Kẻ Trừ Tà source: canonical 327 chapters (2026-10-09)

Result: Drive `NGUỒN TRUYỆN/Truyện chưa dịch - txt/6.1. Kẻ trừ tà/split` holds 327 chương truyện chính in 27 tập
(26 × 12 + Tập 27 = 313-327). `CANON_MAP.txt` there maps every chapter to its slot in the old 356-entry txt.
Tập 1-7 (chương 1-84) are byte-identical to before. 19 chapters were missing from the txt; their Chinese text is in
`split/_bo-sung-can-dich/` waiting for translation, and the 7 tập that hold them carry `_THIEU-CHUONG-<n>` in the vi
and image-prompt file names.

## Evidence chain
- Qidian TOC (m.qidian.com/book/63011/catalog) lists 384 entries with per-chapter character counts: 28 author notes,
  free 第四篇 鬼影 1-19 (repeated again in the VIP volume), 14 外传 (mostly fan works and notes), VIP 240.
  384 - 28 = 356, which is the old txt and the "356 chương" figure. Its titles match the txt in order, all 356.
- novel101.com (332 entries = 327 main + 5 author extras; same order as JD/WeRead) gave the full text of every main
  chapter. Every txt slot was compared to it by 6-gram containment after t2s conversion.
- Findings: 308 of 327 main chapters are in the txt, some under the wrong title (19 slots hold another chapter's
  text, e.g. slot 169 titled 遗骨 holds 始作俑者). 19 chapters are absent: 秘密 26, 34, 38, 40, 50-58, 62, 63;
  迷城 42, 53; 赌神 19, 23. 迷城 25 was posted twice by the author (once mislabelled 第八章 破界).
- The 19 restored chapters were checked against Qidian's character counts (ratio 0.92-0.98) and end on a full
  sentence; 迷城 53 ends with the author's pointer to 第七篇 阴童.

## Superseded
An earlier pass the same day dropped 48 "duplicate" slots and called the 308 chapters complete. The text it kept
was real, but 19 chapters were missing in the middle of the story and the tập split was wrong. That 308-chương
`split` is archived as `_archive/split-308-thieu-19-chuong-20261009/`; the original 356-entry txt split is
`_archive/split-356-chuong-co-lap-20261009/`.

## Image prompts
Reassembled per chapter from the old prompt files. Tập 1-9 reuse the old files unchanged; 33 cut points between
chapters were read by hand (18 moved 1-10 scenes from the automatic guess) and cross-checked against the chapter tags
some prompt files carry. Tags the generator got wrong (scene 220 of old 0265_0276 says chapter 272, the text puts the
door kick at the end of 271) were relabelled to the scene's own chapter. The 19 restored chapters have no prompts yet.

## Restored chapters translated (2026-10-09)
cli-tran (`--series ke-tru-ta`, Gemini 3.1 Pro High) translated all 19, none flagged for review. Checked: no CJK,
no em dash, every chapter ends on a full sentence, 0.92-1.03 vi words per zh character (the other 308 chapters:
median 0.99, p10-p90 0.94-1.03), glossary names used, address shifts to anh/em at the confession in 306 as 307 does.
Titles of 160 and 172 were aligned with their (Thượng) halves 159 and 171. Merged into the 7 tập as plain `_vi.txt`;
the incomplete vi files are in `_archive/split-vi-thieu-chuong-20261009/`.

## Done 2026-10-10
Tập 12, 13, 14, 15, 18, 19, 26 got `_vi_qa.txt` and full image prompts (300 scenes each, Gemini 3.8 Flash High, run by
agy), checked for chapter coverage, scene numbering and stray CJK, then moved into `split/`; the `_THIEU-CHUONG-`
prompt files are in `_archive/split-prompts-thieu-chuong-20261009/`. Music was reallocated for 27 tập by agy
(`KTT_BGM_COMBO_MAPPING_27_TAP.md`); unused tracks and the 29-tập mapping copies were moved to
`3. Kẻ Trừ Tà/_archive/music-cu-29-tap/`. Tập 11-27 titles are in `KTT_YOUTUBE_TITLES_TAP_11-27.md` (praise lines
and two hooks reworked after review).

## Open
- Tập 14 prompts keep one Chinese-name mention ('司马南' on an embroidered robe) as a literal detail of the scene.
- Chap folders, BGM mapping and arc thumbnails were planned for 29 tập; recheck against 27 tập.
