# SFX cues and music schedule

Both are authored into creative.yaml (Kaggle) or job.yaml (local); the tool only renders them.
Sources: memories `sfx-insertion-workflow`, `sfx-library-location`, `sfx-whisper-masking-fix`,
code `Colab/cloud_director.py` (`_filter_sfx_cues`, `_sfx_cue_cap`).

## Timebase

All times are **narration seconds** (the provided SRT, cue 0 = first narration word). The tool
shifts them by the intro-CTA length itself. Never add the CTA offset by hand, never use SRT line
numbers as seconds (dao-si-chap18 put one cue 228s off that way).

## SFX library

`~/.local/share/videotool/sfx/<pack>/` — `binh-thien` (12 files, kiếm hiệp / quân sự) and
`dao-si` (28 files, ma hài: horror stingers + comedy boing/scratch/pop). Pack = `sfx_pack` in
series.yaml. Filenames must match the pack exactly, prefix included
(`freesound_community-owl-hooting-48028.mp3`). Masters on gdrive (`1. sfx Binh thien sach`,
`2. sfx Dao Si`); re-stage with `rclone copy`, never FUSE `cp`.

Loudness spread is −11..−47 dB mean across files, so set `gain_db` per cue from the file's measured
`max_volume`, aiming at a peak ≈ −16 dBFS. Too quiet raw (big gain needed, or skip):
`dao-si/…running-in-grass` (−47, practically unusable), `binh-thien/hit-swing-sword-small-2`
(−41; prefer `sword-slash` unless boosted — chap54 used it at −4 dB).

## Hard limits the box enforces (cue silently dropped otherwise)

- time ≥ 30s (intro/CTA region) and ≤ `voice_end − 25s` (outro region; `voice_end` = the END of the
  last SRT cue — it used to be the START, which silently cut the cap one cue short until 2026-09-19)
- ≥ 30s after the previous KEPT cue — two cues 15s apart lose one
- count ≤ `max(15, voice_end // 420)` (one per ~7 min beyond 15)
- Run `videotool creative lint` (kept/dropped with reasons) and `videotool creative sfx-pin` (quote
  → exact time) instead of simulating the filter by hand. A dropped climax cue is silent.

## Rules `creative lint` blocks the stage on

- Each SFX file **at most 2 times** per episode — the user's rule for every episode (2026-09-21).
- Every chapter of ≥ 5 min keeps at least one cue; lint prints `sfx.per_chapter`. ĐẠO SĨ Chap 22 kept
  all its cues inside the first 12 of 82 minutes and nothing flagged it (2026-09-21).
- `enhance.sfx.pack` written out: the render box does not read series.yaml, so without it the pack is
  guessed from keywords in the script.

## Convention (not enforced — keep it)

- Density: ~1 cue per 6-9 min, clustered at action/scares/punchlines, ~0 during exposition or
  dialogue chapters. Comedy SFX (boing/scratch/pop) ≤1 per 5-8 min, only on punchlines.
- Scan the WHOLE SRT, not just the climax: action beats in the first half count too (a cavalry
  charge, a beast reveal) — picking only from the second half left 56 minutes silent (shadow test
  BT54, 2026-09-19).
- Each file at most 2 times per episode.
- Point SFX sit −8..−15 dB under the voice and are NOT ducked. Whisper/drone/wind files (voice band)
  go lower (≈ −20..−24) — at the point level they mask the narration ("léo nhéo").

## Picking and pinning beats

1. Scan `outputs/captions.srt` (or the QA SRT) for action words: kiếm/đao/chém/tuốt/vung/đâm tới/
   mũi tên/nỏ/ngựa hí/vó ngựa/nổ tung/va chạm/giáng xuống/gầm; for ĐẠO SĨ also ma/hét/gõ cửa/sét.
2. grep the context of every hit and **drop metaphors**: "chấn động lòng", "đâm ra" (jut out),
   "như mũi tên" is fine for a whoosh.
3. Pin inside the cue by character interpolation: `start + (char_index / len(text)) × (end − start)`.
   Never the cue start (1-3s early), never re-run whisper.
4. Match keys as a substring from mid-sentence: a capitalised sentence start ("Một tiếng…") or a
   mistyped diacritic makes the match fail — assert every cue was pinned (chap51, chap54).
5. A beat inside the tail limit → pin to the previous beat of the same climax (dao-si-chap33).

## Music schedule

- Always `ls Music/` first — the track set changes between episodes (chap43, dao-si-chap34).
- `*_music_prompts.txt` has N mood blocks; block i ↔ track i in natural sort order. Some episodes
  ship no prompts file: map by track name/mood.
- Cue shape `{track, start, end, gain_db?}`; `track` = 1-based index or a stem substring.
- Map each track to the chapter span whose mood fits (calm/scenery → gentle, action/climax →
  faster, grief → sorrow). Spans must cover 0 → end of the last SRT cue with no gap.
- Chapter start seconds come from the SRT "Chương N:" cues (or `project.chapters`).
- Unset → all tracks concat + loop. Music bed default −30 dB under the voice.
- Music missing on Kaggle before 2026-07-21 was a wiring bug (fixed `d90b9f3`); still confirm
  `inputs.music` in the early job.yaml check.
