---
phase: 2
title: SFX post-process mix (enhance.sfx)
status: completed
effort: ''
---

# Phase 2: SFX post-process mix (enhance.sfx)

## Overview

Lồng SFX one-shot vào các beat hành động. Mix **hậu kỳ trên mp4 đã render** (remux audio, `-c:v copy`) — không luồn vào render graph → Plan 1 giữ nguyên. Đúng phương pháp đã validate (memory `sfx-insertion-workflow`, chạy thật T11/T12). Beds/ambient để sau.

## Requirements

- Functional: `enhance.sfx: {enabled: bool, pack?: str, cues: [{time, file, gain_db}]}`. `videotool sfx "$JOB"` đọc cue, mix lên `outputs/<preset>.mp4`, ghi đè (hoặc `.sfx.mp4` rồi thay). SFX **không ducked**; mix `amix normalize=0` + `alimiter`. Không có cue / `enabled:false` → no-op.
- Non-functional: `-c:v copy` (không re-encode video); audio re-encode AAC 256k (nhất quán Plan 1); không đè vùng CTA (LLM tránh; tool không bắt buộc).

## Architecture

Module mới `render/sfx_mix.py`: `build_sfx_mix_command(video_in, cues, video_out, intro_offset, audio_bitrate)` → ffmpeg: input 0 = mp4; input i = mỗi file SFX (path trong job folder). filter_complex: mỗi cue `[i:a]volume={gain_db}dB,adelay={ms}:all=1[s{i}]`; `[0:a][s1..sn]amix=inputs=n+1:normalize=0:duration=first[mix]`; `[mix]alimiter=limit=0.95[a]`. Map `0:v` copy + `[a]`. `time` narration-aligned → `ms = round((time + intro_offset)*1000)`.

Service `run_sfx(job_path)`: đọc `job.enhance.sfx`; với mỗi output preset có mp4 → mix. intro_offset = duration(intro_cta) như `run_package`. Ghi ra tmp rồi `os.replace` đè mp4 (an toàn). CLI `sfx "$JOB"`.

Vị trí trong flow: sau `render`, trước `package` (thumbnail/manifest tính trên mp4 đã có SFX).

## Related Code Files

- Create: `src/videotool/render/sfx_mix.py` — build command (thuần, testable) + `mix_sfx_onto(video, cues, out, ...)` chạy ffmpeg.
- Modify: `src/videotool/core/job_spec.py` — `SfxCueSpec(time: float ge0, file: Path, gain_db: float=0.0)`; `EnhanceSpec.sfx: SfxSpec | None = None` (SfxSpec{enabled: bool=True, pack: str|None, cues: list[SfxCueSpec]}).
- Modify: `src/videotool/core/services.py` — `run_sfx(job_path)`.
- Modify: `src/videotool/cli/commands.py` + `main.py` — command `sfx`.

## Implementation Steps

1. **Schema**: `SfxCueSpec(time ge0, file: Path, gain_db: float=0.0)`; `SfxSpec(enabled=True, pack: str|None=None, cues: list[SfxCueSpec]=[])`; `EnhanceSpec.sfx: SfxSpec | None = None`. Validate file path relative trong job folder (như particle_overlay) — chặn escape.
2. **sfx_mix.build_sfx_mix_command**: dựng inputs + filter_complex như Architecture. Cue rỗng → trả None (caller skip). `-c:v copy`, `-c:a aac -b:a 256k -ar 48000 -ac 2`.
3. **sfx_mix.mix_sfx_onto**: chạy command (subprocess pattern như music_loop `_run`), ghi tmp `.videotool/tmp/sfx-<preset>.mp4` rồi `os.replace` đè output.
4. **services.run_sfx**: validate; nếu `sfx` None / `enabled:false` / cues rỗng → return sớm (no-op). Với mỗi `outputs/<preset>.mp4` tồn tại → mix với intro_offset.
5. **CLI**: `sfx "$JOB"` → `run_sfx`; báo số cue đã lồng / no-op.

## Success Criteria

- [ ] `enhance.sfx` None / enabled:false / cues rỗng → `sfx` no-op, mp4 không đổi.
- [ ] N cue → command có N+1 input, adelay đúng `(time+offset)*1000`ms, `amix normalize=0` + `alimiter`, `-c:v copy`, `-b:a 256k`.
- [ ] SFX không ducked (không sidechain), voice/music giữ nguyên mức.
- [ ] file cue ngoài job folder → ValidationError (chống escape).
- [ ] mp4 sau mix: video stream copy (ffprobe: cùng codec/độ dài), audio aac.

## Risk Assessment

- **Timing lệch = phản cảm (red line)**: tool chỉ đặt đúng `time` LLM cấp; độ chính xác pin là việc của Phase 3 (char-interpolation). Tool phải cộng offset đúng.
- **amix hạ âm lượng tổng** (`normalize=0` giữ mức, nhưng tổng biên có thể clip) → `alimiter=0.95` chặn; test có limiter.
- **Đè mp4 gốc**: ghi tmp rồi `os.replace`; nếu ffmpeg fail, giữ mp4 cũ (không xoá trước khi thành công).
- **Nhiều preset** (shorts): mix từng mp4 với cùng cue (cùng offset). Đảm bảo lặp qua tất cả outputs.
