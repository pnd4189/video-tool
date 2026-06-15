---
slug: full-tier-effects-and-moods
status: done
created: 2026-06-15
completed: 2026-06-15
branch: feat/parallax-2-5d
---

# Plan: bỏ progress bar + Nhóm A FX (mood-driven) + BYO atmosphere

## Decisions (chốt qua nhiều lượt /ask)
- **Bỏ progress bar khỏi MỌI job** (gỡ hẳn feature).
- **Nhóm A filter-only** (free, không asset): vignette, grain, glow, flicker, color-grade. Mood-driven.
- **Mood preset**: `clean/melancholy/cozy/horror/action` → gói cờ Nhóm A. Agent gợi ý mood khi /make-video, ghi vào job.yaml.
- **BYO atmosphere** (mưa/tuyết/bokeh): tái dùng slot input `inputs.particle_overlay` có sẵn, blend `screen`. Asset do user cung cấp (tải CC0 / render Remotion local) — KHÔNG bundle. Verify bằng clip placeholder.
- **Parallax** đã xong, bật qua hint (không đụng).
- FX chỉ chạy ở tier full (đã re-encode 1 lần) → không thêm pass, chậm biên.

## Touchpoints (scout)
- `core/job_spec.py:124 EnhanceSpec` — bỏ `progress_bar`; thêm `mood`, `vignette/grain/glow/flicker` (bool|None), `color_grade` (Literal|None), `atmosphere` (bool). Bỏ `progress_bar` khỏi `ENHANCE_FEATURES`.
- `core/timeline.py:51` — bỏ `enhance_progress_bar`; thêm `enhance_vignette/grain/glow/flicker/atmosphere` + `enhance_color_grade`; map từ enhance.
- `render/overlay_graph.py` — bỏ progress-bar block; thêm chuỗi filter Nhóm A (single-input) + atmosphere screen-blend (reuse particle input slot); cập nhật `needs_video_overlay`.
- `tests/test_overlay_graph.py`, `test_enhance_tier.py` — cập nhật (bỏ progress bar; thêm mood/FX).
- `AGENTS.md` — mood catalog + agent advice; bỏ progress bar khỏi mô tả.

## Mood → Nhóm A (bảng phân giải, trong EnhanceSpec)
| mood | vignette | grain | glow | flicker | color_grade |
|---|---|---|---|---|---|
| clean | ✓ | ✓ | | | warm |
| melancholy | ✓ | ✓ | | | cold |
| cozy | ✓ | | ✓ | | warm |
| horror | ✓ | ✓ | ✓ | | cold |
| action | | ✓ | | ✓ | neutral |
Override per-effect: field != None thắng mood; mood=None + field=None → off.

## FFmpeg filters (single-input, ghép trong build_video_overlay)
- vignette: `vignette=PI/5`
- grain: `noise=alls=10:allf=t`
- color_grade warm: `colorbalance=rs=.06:gs=.02:bs=-.06`; cold: `colorbalance=rs=-.06:gs=0:bs=.06`; neutral: `eq=contrast=1.08:saturation=1.06`
- glow: `split=2[g0][g1];[g1]gblur=sigma=14,eq=brightness=0.05[g2];[g0][g2]blend=all_mode=screen`
- flicker: `eq=brightness='0.03*sin(2*PI*t*3)':eval=frame`
- atmosphere: `[cur][ovl]blend=all_mode=screen` (ovl = particle input slot có sẵn)

## Phases
1. Schema: EnhanceSpec (bỏ progress_bar, thêm mood/FX/atmosphere + resolver) + ENHANCE_FEATURES.
2. Timeline: bỏ progress field, thêm FX fields, map từ enhance (mood-resolved).
3. overlay_graph: bỏ progress block, thêm filters Nhóm A + atmosphere; needs_video_overlay.
4. Tests: cập nhật cũ + thêm test mood/FX/atmosphere; verify render placeholder.
5. Docs: AGENTS.md mood catalog + advice; plan status done.

## Out of scope (round sau)
- Bundle asset CC0 (mưa/tuyết) — user tự cấp.
- Nhiều overlay clip cùng lúc (giờ 1 slot atmosphere). Remotion generator project.

## Success
- `enhance.mood: cozy` → render full ra video có vignette+glow+grade ấm; ffprobe h264/aac đúng res.
- progress bar không còn ở bất kỳ job nào.
- `pytest -q` xanh (cập nhật test cũ), không hồi quy light/parallax.
