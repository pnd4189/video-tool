# Brainstorm — make-video feature adjustments (round 2)

Date: 2026-05-29. Status: design approved by user, ready for `/ck:plan`.

## Problem statement

`/make-video` pipeline works but needs 6 adjustments for the audio-story YouTube flow.
All confirmed decisions in `AGENTS.md` stay locked (motion 0.30/1.22, no waveform, no Whisper).

## Confirmed requirements (from user Q&A)

1. **No auto shorts.** Only render `youtube-16x9` by default; `shorts-9x16` only when user asks.
2. **Ending image** (provided in asset folder): append as a real **+10s** outro after voice ends.
   Music keeps playing during this 10s.
3. **Intro thumbnail** (template, no text): embed into the **first 10s of the voice timeline** —
   NO added time. It overlays the start; voice keeps running underneath.
4. **Music default −28 dB** (was −18). PLUS: if asset folder has **multiple** instrument tracks,
   concat ALL of them in order, then loop until end of video (incl. the +10s ending).
5. **rclone gdrive staging.** Assets live on a gdrive **mount** path. Copy job folder → local,
   render locally, copy outputs back to gdrive into a new `Output/` subfolder of the original
   folder, then delete the local staging copy. NEVER delete files on the mount.
6. **Effects review (rain/wind/particles).** Report feasibility only this round; defer implementation.

### Derived duration model

```
total video = voice + 10
  0 .. 10s          intro thumbnail   (voice playing)
  10s .. voice_end  storyboard images (even-split over voice − 10)
  voice_end .. +10s  ending image     (voice silent, music continues)
audio = voice + 10s silence (apad), music looped to cover total
```

## Acceptance criteria

- Default run → only `youtube-16x9.mp4`; no shorts file. Shorts appears only with hint.
- When `intro_image` set: first 10s shows it, total = voice+10, middle images split (voice−10).
- When `ending_image` set: last 10s shows it, voice silent there, music audible.
- Music: rendered audio at ~−28 dB under voice; multiple tracks concatenated then looped to total.
- gdrive job: outputs land in `<original-folder>/Output/`, local staging removed, mount untouched.
- 66 existing tests stay green (snapshot tests updated for new −28 dB default — not a regression).

## Scope boundary (OUT)

- No rain/wind/particle implementation (item 6 = report only).
- No new render presets, no Whisper, no waveform.
- INTRO/OUTRO fixed at 10s constants (not user-configurable this round — YAGNI).

## Design (approved)

### Item 1 — no auto shorts
- `write_job_template` (`core/job_spec.py:158`) and `plan_storyboard` (`cli/storyboard_commands.py:28`):
  default `outputs: [youtube-16x9]` only.
- `make-video.md` + `AGENTS.md`: default `render --preset youtube-16x9`; add `shorts-9x16` to
  outputs + render only when hint contains shorts/9x16/--all.

### Item 2 & 3 — intro / ending images
- `InputSpec` (`core/job_spec.py:31`): add `intro_image: Path | None`, `ending_image: Path | None`.
- `core/storyboard.py`: constants `INTRO_SECONDS = 10`, `OUTRO_SECONDS = 10`.
- `auto_storyboard` (`cli/storyboard_commands.py:51`) reads the two fields and builds scene list:
  - intro present → scene 1 = intro 10s; image split base = `voice − INTRO_SECONDS`.
  - ending present → last scene = ending 10s (pure extension).
  - sum(scene durations) = voice + OUTRO_SECONDS.
  - motion = `slow-push` for intro/outro.
- Guard: if `voice <= INTRO_SECONDS`, skip intro (warn).
- Detection of which file is intro/ending = agent (skill) job: scan filenames/subfolders
  (`thumb*` → intro; `*end*`/`outro`/"ảnh end" → ending), write resolved paths into job.yaml.
  Schema only holds paths (no hardcoded names).

### Item 4 + multi-music
- `AudioSpec.music_gain_db` (`core/job_spec.py:79`): `-18.0` → `-28.0`.
- `inputs.music` may point to a **folder**: `_stage_music` (`core/services.py:227`) expands a dir
  to a natural-sorted list of audio files. `prepare_seamless_music` (`render/music_loop.py`)
  accepts a list → concat in order → loop to `target_duration`.
- `target_duration` = total video (voice + OUTRO_SECONDS), not just voice.
- Voice gets `apad` of OUTRO_SECONDS silence so amix(duration=first) covers the outro
  (in `render/audio_graph.py` or staged in services). Duck releases during silence → music
  audible at −28 dB in the outro.

### Item 5 — rclone staging (skill-level, no core code)
Workflow added to `make-video.md` + `AGENTS.md`:
1. Receive gdrive mount folder path.
2. Copy folder → local staging (e.g. `~/.cache/videotool/<job>/`).
3. Run init→storyboard→validate→render→package locally.
4. Copy `outputs/` → `<gdrive-folder>/Output/` (new subfolder in the original folder).
5. `rm -rf` the local staging dir ONLY. Never `rm` on the mount.
6. Report gdrive output paths + local space reclaimed.
- Safety: staging dir is outside the mount; rm targets staging only.

### Item 6 — feasibility report (defer)
Rain/wind/particle overlay can ride the per-clip encode in the segmented path (each clip already
encodes zoompan) → no extra mux pass, only +CPU (~10–20% est.). Inline path = one filtergraph too.
Contrast: waveform overlay was rejected because it forces re-encode at the `-c:v copy` mux.
Implementation candidates: looping rain PNG overlay, or generated `noise`/`fractal` filter.
Defer to a later round.

## Touchpoints

`core/job_spec.py`, `core/storyboard.py`, `cli/storyboard_commands.py`, `core/services.py`,
`render/music_loop.py`, `render/audio_graph.py`, `.claude/commands/make-video.md`, `AGENTS.md`, tests.

## Risks

- `core/services.py` already 294 lines (>200 flag) — extract a helper for music/apad logic.
- Changing `music_gain_db` default breaks audio-graph snapshot tests → update expectations
  (verified-decision change, not a bug; document in test).
- Voice shorter than 10s → intro guard required.
- Multi-music with mixed sample rates/codecs → concat must normalize (resample) before loop.

## Open questions

None blocking. (Sample-rate normalization handled in implementation; INTRO/OUTRO kept as constants.)

## Next step

`/ck:plan` (default mode) — new-feature expansion with light test updates. Lock −28 dB snapshot
change in the relevant phase. Pass this report as context.
