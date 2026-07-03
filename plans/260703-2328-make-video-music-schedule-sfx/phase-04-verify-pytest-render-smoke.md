---
phase: 4
title: Verify (pytest + render smoke)
status: completed
effort: ''
---

# Phase 4: Verify (pytest + render smoke)

## Overview

Unit test cho schema + music-schedule staging + sfx-mix command; full suite xanh; render smoke thật để nghe nhạc đổi track đúng mốc + SFX rơi đúng.

## Related Code Files

- Create/Modify: `tests/test_music_loop.py` (schedule), `tests/test_job_spec.py` (schema music_schedule + sfx), new `tests/test_sfx_mix.py`, `tests/test_cli_commands.py` (sfx no-op).

## Implementation Steps

1. **Schema tests**: `music_schedule` cue chồng lấn → error; end<=start → error; backward-compat (không có field → None). `enhance.sfx` file ngoài folder → error; cues rỗng OK.
2. **prepare_scheduled_music**: fixture 2–3 track ngắn + cues → FLAC dài = target; đủ đoạn; gain áp. No-schedule nhánh cũ không đổi (test byte-đồng nhất command music hiện có vẫn pass).
3. **sfx_mix.build_sfx_mix_command**: 3 cue → assert N+1 input, `adelay=<ms>` đúng (gồm intro_offset), `amix=inputs=4:normalize=0`, `alimiter`, `-c:v copy`, `-b:a 256k`. Cue rỗng → None.
4. **CLI**: `sfx` với `enhance.sfx=None` → no-op exit 0.
5. **Full suite**: `.venv/bin/python -m pytest -q` xanh (≥175 + mới).
6. **Render smoke (thật, sample ngắn)**: job có `music_schedule` 2 cue + `enhance.sfx` 2 cue → `render` → `sfx` → `package`. Kiểm: ffprobe mp4 (h264 copy + aac 256k, đủ độ dài); nghe thử ranh giới nhạc + SFX đúng chỗ (hoặc kiểm command/filtergraph nếu không render nổi). Xác nhận không có SFX trong 30s đầu/25s cuối.

## Success Criteria

- [ ] Tất cả test schema/music/sfx/cli pass.
- [ ] No-schedule + no-sfx → hành vi Plan 1 không đổi (test).
- [ ] `pytest -q` xanh.
- [ ] Smoke: mp4 hợp lệ; nhạc đổi track đúng mốc; SFX đúng beat, không ducked, không đè CTA.

## Risk Assessment

- **Không render nổi máy local** (dài) → dùng sample rất ngắn + dry-run command assert.
- **CTA offset**: test 1 ca có intro_cta để chắc offset cộng đúng ở cả music + sfx.
