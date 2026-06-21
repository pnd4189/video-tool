---
phase: 4
title: Docs mood-map + memory
status: completed
priority: P3
dependencies:
  - 1
  - 2
  - 3
effort: ''
---

# Phase 4: Docs mood-map + memory

## Overview
Sau khi đủ 4 kind overlay mới, cập nhật mood-map trong AGENTS.md + memory `overlay-fx-library` để `/make-video` full FX biết các overlay mới + chọn đúng theo mood truyện.

## Requirements
- Functional: AGENTS.md "Atmospheric overlay" decision liệt kê kind mới + mood map; memory cập nhật danh sách + cách regenerate. Ghi cách chạy `scripts/gen_overlay.py` + `Colab/qi_wisps_overlay_colab.py`.
- Non-functional: KHÔNG nối generator vào pipeline (giữ nguyên tắc offline asset tool); doc ngắn gọn (AGENTS.md không quá ~150 dòng).

## Architecture
- AGENTS.md "Atmospheric overlay" mood-map mở rộng: đêm/quê → `fireflies-*`; đốt bùa/action → `ember-*`; nội thất bỏ hoang/cũ → `dust-*` (tinh chỉnh, dust cũ map old-film); mystical/linh khí → `qi-*` (cạnh `smoke/particles/cosmos`). Thêm 1 câu: overlay `-gen-*` sinh bằng `scripts/gen_overlay.py` (numpy) + `Colab/qi_wisps_overlay_colab.py` (GLSL Colab).
- Memory `overlay-fx-library.md`: thêm 4 file `*-gen-01.mp4` vào danh sách kind; thêm mục "Regenerate" trỏ script; giữ note durable-dir + screen-blend RGB.

## Related Code Files
- Modify: `AGENTS.md` (mục "Atmospheric overlay = pick from local CC0 library" — thêm kind `-gen-*` + cách sinh)
- Modify: `/home/dung/.claude/projects/-home-dung-VIBE-CODING-video-tool/memory/overlay-fx-library.md` + `MEMORY.md` index dòng tương ứng

## Implementation Steps
1. Đọc mục "Atmospheric overlay" hiện tại trong AGENTS.md; thêm 4 kind mới vào mood-map + 1 câu về generator (giữ ngắn). Cập nhật ngày quyết định.
2. Cập nhật memory `overlay-fx-library.md`: thêm `fireflies-gen-01`/`ember-gen-01`/`dust-gen-01`/`qi-gen-01` + mục Regenerate (lệnh `scripts/gen_overlay.py --preset <kind>`; qi → Colab notebook).
3. Cập nhật dòng index trong `MEMORY.md` nếu cần.
4. Kiểm AGENTS.md không vượt ~150 dòng (nếu phình → rút gọn chỗ khác hoặc đẩy chi tiết vào docs/).

## Success Criteria
- [ ] AGENTS.md mood-map có đủ fireflies/ember/dust/qi + cách sinh; vẫn ≤ ~150 dòng.
- [ ] Memory `overlay-fx-library` liệt kê 4 overlay mới + cách regenerate; MEMORY.md index khớp.
- [ ] Không có thay đổi nào nối generator vào render pipeline (vẫn offline asset tool).

## Risk Assessment
- **AGENTS.md phình quá 150 dòng** → rút gọn, đẩy chi tiết engine vào `docs/` hoặc plan này.
- **Mood-map mâu thuẫn** (dust cũ vs mới) → nêu rõ dust dùng cho cả old-film lẫn nội thất bỏ hoang.
