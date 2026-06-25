# Design Guidelines & Technical Specifications

## Motion & Visual Design

### Ken Burns Motion

**Purpose:** Animate static images to defeat YouTube's static-frame penalty detection.

**Parameters** (`src/videotool/render/video_filters.py`):

```python
ZOOM_AMPLITUDE = 0.30       # Zoom multiplier per second
PAN_ZOOM = 1.22             # Base scale factor
```

**Behavior:**
- Slow random zoom in/out at 0.30× per second
- Pan across image as zoom progresses
- Subtle enough to feel natural, obvious enough to avoid YouTube flagging as static

**Why these values:**
- 0.12 (old default) too slow for 1h+ videos (human eye barely notices motion)
- 0.30 visible per-second without jarring
- 1.22 pan zoom keeps subject in frame (tight crop avoid overrotate)
- Decided 2026-05-28; bumped from 0.12

**Do NOT lower without user confirmation.**

### Intro & Ending Image Overlay

**Constraint:** Both overlay narration (no added time).

**Timing:**
- **Intro image:** Overlays first 10s of narration (0:00–0:10)
- **Ending image:** Overlays last 10s of narration (voice_end - 10s to voice_end)
- **No extension:** If ending image exists, it does NOT extend video duration

**Why:**
- Ending card must be flush with voice end (spliced outro CTA card stays in sync)
- Old approach (ending extends +10s) caused outro CTA lag of 10s
- Decided 2026-06-13

**Example:**
```
Voice: 1:00:00 (60 minutes)
Ending image requested

Ending image overlays:
  - Start: 0:59:50 (60 min - 10s)
  - Duration: 10s
  - End: 1:00:00 (exactly voice end)

Video total: 1:00:00 (unchanged)
```

### B-Roll Clip Interleaving

**Requirement:** Never drop video clips; spread by story order, full duration kept.

**Algorithm:**
1. Discover scene images + video clips (scene-001.jpg, scene-001.mp4, etc.)
2. Interleave by story order (alternating images/clips when both present)
3. For each clip: use real duration (no trim unless exceeds remaining narration)
4. For each image: Ken Burns or parallax animation

**Example:**
```
Story chapters (voice narration):
  Chap 1 (0–5s): scene-001 image
  Chap 2 (5–10s): scene-002 video (3s clip)
  Chap 3 (10–20s): scene-003 image
  Chap 4 (20–25s): scene-004 video (5s clip)

Storyboard timeline:
  [image 5s] + [video 3s] + [image 10s] + [video 5s] = 23s total
```

**Interleave order matters:** Preserve narrative flow (scene-001, then scene-002, not jumbled).

**Decided 2026-06-13.**

---

## Audio Design

### Loudness Target

**Standard:** −14 LUFS (YouTube loudness spec)

**Tolerance:** ±1 LUFS drift acceptable (not audible)

**Implementation:**
```bash
loudnorm=I=-14:TP=-1:LRA=11
```

| Parameter | Value | Purpose |
|-----------|-------|---------|
| I (integrated) | −14 | Target loudness (YouTube spec) |
| TP (true peak) | −1 | Prevent digital clipping |
| LRA (loudness range) | 11 | Don't compress dynamic range too tight |

**Single-pass:** `loudnorm` runs once at mux time (no iterative adjustment).

**Why −14 not −16:** YouTube auto-normalizes to −14; setting −16 causes re-normalize on upload (audio quality loss).

### Music Bed Level

**Default:** −30 dB (quiet, never competes with narration)

**Channel override (audio-story):** −30 dB (same; decided 2026-05-31)

**User-adjustable:** Via `audio.music_gain_db` in job.yaml

```yaml
audio:
  music_gain_db: -30   # −30 dB quiet bed
  # or:
  music_gain_db: -20   # Louder if user wants
  # or:
  music_gain_db: -50   # Barely audible ambient
```

**Sidechain duck:** Active by default (`audio.duck: true`)
- Music automatically pulls back when voice present
- Threshold 0.05, ratio 8:1 (strong), attack 5ms (fast), release 400ms (slow fade out)
- No manual gain curves needed

**Why sidechain matters:**
- Static −30 dB might sound loud during quiet voice passages
- Dynamic duck feels more natural; music recedes when narrator speaks
- Prevents "muddy mix" (voice + music competing)

### Voice Gain

**Default:** 0 dB (no adjustment)

**Adjustable:** Via `audio.voice_gain_db` (range −20 to +20 dB)

**When to adjust:**
- Voice recorded too quiet: +3 to +6 dB
- Voice recorded too loud: −3 to −6 dB
- Loudnorm handles final level, voice_gain_db is pre-adjustment

### Normalization Bypass

**For advanced users:** `audio.normalize_lufs: null` skips loudnorm entirely

```yaml
audio:
  voice_gain_db: -6
  music_gain_db: -25
  normalize_lufs: null   # Skip final loudnorm; gains are absolute
```

**Not recommended:** Requires manual loudness metering afterward.

---

## Subtitle & Caption Design

### Subtitle Timing (Script Alignment)

**Principle:** Whisper provides timing; script provides wording.

**Process:**
1. Whisper transcribes audio (e.g., "the quick brown fox jumps")
2. Script provides intended text (e.g., "The quick brown fox jumps over the lazy dog")
3. Align script onto whisper span using **character-position interpolation**

**Algorithm:**
```
Whisper segment: "the quick brown fox" (0:00:00–0:00:05, 5 seconds)
Script sentence: "The quick brown fox jumps over the lazy dog"

Align:
  'T' (position 0 in script, 0% of 4 chars) → 0:00:00
  'h' (position 1 in script, 25%) → 0:00:01.25
  'e' (position 2, 50%) → 0:00:02.5
  ' ' (position 3, 75%) → 0:00:03.75
  'q' (position 4, 100%) → 0:00:05 (span end)
  (remaining "umps over..." extends beyond span → next segment)
```

**Why NOT segment-start:**
- Whisper segments ≠ sentence boundaries
- Segment-start would jump timing (0:00:00 → 0:00:05 gap)
- Character-position is monotonic, bounded, robust
- Validated 2026-06-24 with SFX insertion

**Timing tolerance:** ±100ms of character position acceptable (human perception).

### Chapter Timing

**Source:** Aligned transcript (from `transcribe` output)

**Detection:** Find "Chương" markers in transcript

**Rules:**
- **≥3 chapters:** Auto-derive timestamps from alignment
- **<3 chapters:** Skip auto-gen; hand-write `chapters.json`

**Example** (hand-written for <3 chapters):
```json
{
  "chapters": [
    {"name": "Giới thiệu", "start_time": 0},
    {"name": "Chương 1", "start_time": 30},
    {"name": "Chương 2", "start_time": 600}
  ]
}
```

**YouTube format:** Paste `description.txt` (generated from template) into YouTube description field; YouTube auto-parses chapters.

**Accuracy target:** ±1s of chapter marker (good enough for viewer navigation).

---

## Tier Light Design

**Philosophy:** Speed-to-publish beats polish.

### Characteristics

- **Encode:** libx264 CRF 23, single pass, `-c:v copy` mux (no re-encode)
- **Duration:** ~1h real-time for 1h audio
- **Subtitle:** None (YouTube auto-CC sufficient)
- **FX:** None (Ken Burns motion only)
- **Audio:** Voice + music sidechain + −14 LUFS loudnorm
- **Use case:** Weekly release pace, budget-conscious creators

### Codec Stack

```
Input: voice.wav + media/ (images/clips) + music.mp3
  ↓
Audio: voice → atempo → sidechain → amix → loudnorm → AAC 128kbps
Video: media → ken-burns → xfade → H.264 (CRF 23, libx264-balanced)
  ↓
Output: youtube-16x9.mp4 (1920×1080)
```

### Motion Spec

- **Ken Burns:** ZOOM_AMPLITUDE=0.30, PAN_ZOOM=1.22
- **Transition:** Crossfade 0.5s between scenes
- **Duration:** Image duration from timeline (calculated from narration)

---

## Tier Full Design

**Philosophy:** Premium channel episodes, flagship releases.

### Characteristics

- **Encode:** libx264 CRF 22, **single re-encode** (burns overlays + mood + subtitles)
- **Duration:** ~2–3h real-time for 1h audio
- **Subtitle:** Yes, whisper-aligned via script
- **FX:** Mood (5 presets) + optional atmosphere overlay
- **Audio:** Same as light (voice, music, loudnorm)
- **Use case:** Premium episodes, promotional content

### Tier Branching

**Both tiers share:**
- Audio chain (sidechain, loudnorm)
- Ken Burns motion
- B-roll interleave
- Subtitle alignment (if script provided)

**Full-tier only:**
- Single re-encode (efficiency: all overlays burned at once)
- Mood FX (vignette, grain, glow, flicker, color-grade)
- Atmosphere overlay (CC0 library)

**Why single re-encode:**
- Subtitle burn requires re-encode anyway
- Mood filters cheap (GPU filter, not codec-intensive)
- Atmosphere overlay (screen blend) cheap
- One pass vs two = faster than naive "render + overlay separately"

---

## Mood FX Presets

**Filter-only**, independent of tier (tier=full does NOT auto-enable mood).

### Clean

- **Effect:** Subtle vignette (edge darkening)
- **Use:** Light, uplifting, professional tone
- **Filters:** `vignette=1:1:1.2:0.06` (darkening 6%)

### Melancholy

- **Effects:** Grain (film noise) + vignette
- **Use:** Sad, contemplative, old-film aesthetic
- **Filters:** `grain=strength=0.05, vignette=1:1:1.2:0.08`
- **Warning:** Grain auto-enables; if file balloons (~700× size), add `enhance.grain: false`

### Cozy

- **Effects:** Warm color shift + soft glow
- **Use:** Comfortable, intimate, warm tone
- **Filters:** `colortemperature=8000, glow=glitch=0` (warm + soft focus)

### Horror

- **Effects:** Flicker + high contrast
- **Use:** Suspense, tension, scary tone
- **Filters:** `flicker=intensity=0.1, curves=presets=increase_contrast`

### Action

- **Effects:** Saturated color + high contrast
- **Use:** Energy, excitement, dynamic tone
- **Filters:** `hue=s=1.4, curves=presets=increase_contrast` (oversaturate, boost blacks)

### Mood Overrides

Fine-tune per job:

```yaml
enhance:
  mood: melancholy
  grain: false        # Override: no grain for this job
  glow: false         # Override: disable glow (if atmosphere on, prevents wash-out)
```

**Decided 2026-06-15.**

---

## Atmosphere Overlays

**CC0 library** at `~/.local/share/videotool/overlays/` (durable XDG data dir).

### Naming Convention

```
{kind}-{source}-{id}.mp4

Examples:
  rain-forfilmcreation-001.mp4
  snow-forfilmcreation-002.mp4
  fire-fxelements-003.mp4
  fireflies-gen-001.mp4       (generated locally)
  qi-gen-001.mp4              (generated on Colab)
  dust-gen-001.mp4            (generated locally)
  particles-gen-001.mp4       (generated mix)
  cosmos-generated.mp4        (starfield)
  smoke-fxelements-004.mp4
```

### Mood Map (Suggestions)

| Mood | Suggested Atmosphere | Why |
|------|----------------------|-----|
| Melancholy | rain-* | Tears, sadness, moody weather |
| Cozy | snow-* | Winter comfort, quiet blanket |
| Horror | fire-*, smoke-* | Danger, burning, chaos |
| Action | fire-*, smoke-* | Energy, destruction, high stakes |
| Mystical | qi-gen-*, particles-* | Spiritual, magical, ethereal |
| Spiritual | fireflies-gen-*, qi-gen-* | Presence, light, wonder |
| Old-film | dust-*, dust-gen-* | Decay, abandonment, memory |
| Summer/Rural | fireflies-gen-* | Nostalgic, pastoral |
| Dreamy | particles-*, cosmos-* | Surreal, infinite, unconscious |

### Overlay Blending

**Mode:** Screen (lighten)

```
overlay=format=rgb  # NOT yuv420p (causes magenta tint)
```

**Why RGB not yuv420p:**
- Screen blend works in linear RGB color space
- yuv420p blending tints whole frame magenta (chroma subsampling artifact)
- Fixed 2026-06-18; do NOT revert

**Duration:** Looped/trimmed to match scene duration

**Opacity:** Full (no transparency control yet; consider future enhancement)

### Generate Locally

```bash
# Numpy point-sprite fireflies
.venv/bin/python scripts/gen_overlay.py --preset fireflies --output fireflies-gen-001.mp4

# Particle ember
.venv/bin/python scripts/gen_overlay.py --preset ember --output ember-gen-001.mp4

# Dust particles
.venv/bin/python scripts/gen_overlay.py --preset dust --output dust-gen-001.mp4
```

**Size:** ~100MB per 1h loop

### Generate on Colab (GLSL qi-wisps)

```
Upload: Colab/qi_wisps_overlay_colab.py
Run on GPU → Download qi-gen-*.mp4
```

**Quality:** Higher than CPU point-sprite (GLSL shader)

**Speed:** ~2–5 min on Colab GPU

---

## Progress Bar (Removed)

**Status:** No-op key; removed from every job.

**History:**
- V1: Optional `enhance.progress_bar: true`
- Later: "Sweezy-style" viewer-side progress considered better UX
- 2026-06-15: Removed. Key now ignored if present in legacy job.yaml

**For creators:** Let YouTube handle progress bar; no tool support needed.

---

## Shorts (9:16)

**Default:** `youtube-16x9` (16:9 long-form only)

**Add Shorts only when user asks:**

```yaml
outputs:
  - preset: youtube-16x9
  - preset: shorts-9x16
```

**Rendering:**
```bash
videotool render job.yaml --all  # Renders both
```

**Aspect ratio:** 1080×1920 (portrait)

**Ken Burns adapted:** Motion scaled to portrait (pan left-right instead of full-frame)

**Why opt-in:** Shorts != long-form (different audience, different workflow); don't force creation.

---

## Validation & Handoff

### Validation Checklist (Before /Make-Video)

- [ ] voice.wav exists, >1s duration
- [ ] media/ folder has ≥1 image
- [ ] music/ folder present (can be empty)
- [ ] Intro image auto-detected (if present)
- [ ] Ending image auto-detected (if present)
- [ ] job.yaml `policy: allow-missing-local` (for no asset-index.yaml)
- [ ] job.yaml `captions.mode: off` (for light jobs)

### Handoff to Render

**JobSpec is the contract:**
- All config locked in before render (no mid-render changes)
- Schema validation ensures consistency
- Services orchestrator follows script (no improvisation)

**Output format fixed:**
- `outputs/youtube-16x9.mp4` (codec h264, aac, 1920×1080)
- `outputs/thumbnail-1280x720.jpg` (primary)
- `outputs/description.txt` (YouTube-ready)
- `outputs/package-manifest.json` (metadata)

---

## Known Issues & Mitigations

### Issue: Glow Washes Out Fireflies Overlay

**Symptom:** When `enhance.mood: horror` + `atmosphere: true` + fireflies overlay, glow dims the particles.

**Cause:** Glow (brightness boost) happens after screen-blend, reducing particle visibility.

**Mitigation:** Add `enhance.glow: false` to job.yaml when atmosphere on.

```yaml
enhance:
  mood: horror
  glow: false          # Disable glow with atmosphere
  atmosphere: true
  particle_overlay: fireflies-gen-001.mp4
```

**Decided 2026-06-21.**

### Issue: Particle Overlay Path Escapes Job Folder

**Symptom:** `particle_overlay: ../../../etc/passwd` breaks validation.

**Cause:** Validation regex too loose.

**Fixed:** Validation now checks `(job_dir / path).resolve()` stays within `job_dir.resolve()`.

**For users:** Always use relative paths inside job folder (e.g., `../../overlays/rain-001.mp4` is OK if overlays folder is sibling).

**Decided 2026-06-21.**

### Issue: <3 Chapters → No Auto-Generated chapters.json

**Symptom:** Transcript "Chương" markers <3; `transcribe` skips `chapters.json`.

**Workaround:** Hand-write `chapters.json`:

```json
{
  "chapters": [
    {"name": "Giới thiệu", "start_time": 0},
    {"name": "Nội dung chính", "start_time": 30}
  ]
}
```

Paste into YouTube description field; YouTube auto-parses.

**Decided 2026-06-21.**

---

## Reference: Motion Tuning

If ever you need to adjust Ken Burns:

**File:** `src/videotool/render/video_filters.py`

```python
ZOOM_AMPLITUDE = 0.30       # Current: bumped from 0.12
PAN_ZOOM = 1.22             # Current: tuned for 1080p framing

# If lowering:
# - Test on real 1h+ videos (small images hard to judge)
# - Confirm with user first (decided 2026-05-28)
# - Note decision in CLAUDE.md "Confirmed decisions"
```

**Do NOT change without user sign-off.**

---

## Reference: Loudness Testing

```bash
# Measure final video loudness
ffmpeg -i outputs/youtube-16x9.mp4 -af "ebur128=framelog=verbose:peak=true" -f null - 2>&1 | grep -E "I:|LRA:|TP:"

# Expected:
#   I: -14.0 LUFS (±1 tolerance)
#   TP: -1.0 dBFS (no clipping)
#   LRA: 11.0 LU (dynamic range preserved)
```

---

## Next Steps

1. **Tier selection:** Is this a light job (weekly release) or full job (flagship episode)?
2. **Motion review:** Check Ken Burns looks natural (scan first 10s of video)
3. **Subtitle review (full only):** Read captions, confirm alignment with narration
4. **Loudness check:** Verify final video at −14 LUFS ±1
5. **Upload:** Paste `description.txt` into YouTube; YouTube auto-handles chapters

See [CLAUDE.md](../CLAUDE.md) for full workflow reference.
