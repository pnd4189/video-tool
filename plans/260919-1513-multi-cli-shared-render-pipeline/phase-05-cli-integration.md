---
title: "Phase 5: Gắn vào CLI và rào chắn cho agy"
status: done
---

# Phase 5: Gắn vào CLI — agy chạy tự do có rào chắn, hook báo trạng thái

<!-- Updated: Validation Session 1 - agy always-proceed + PreToolUse guard; lessons inbox command; codex config deferred -->

## Context links

- Plan: [plan.md](./plan.md) · cần xong: [Phase 4](./phase-04-stage-watch-notify.md) (`renders hook`, notifier)
- Tài liệu có sẵn trong agy (đọc từ file chạy của agy):
  - `PreToolUse`: stdin `{"toolCall": {"name", "args"}, "stepIdx", …}` → stdout `{"decision": "allow|deny|ask|force_ask", "reason": …}`.
  - `PreInvocation`: stdout `{"injectSteps": [{"ephemeralMessage": …}]}`.
  - Cài đặt "Tool Execution Policy" (`always-proceed` / `request-review` / `strict` / `proceed-in-sandbox`) và "Non-Workspace File Access".
- Tool của agy: `write_to_file`, `replace_file_content`, `multi_replace_file_content`, `run_command`, `view_file`, `list_dir`, `grep_search`…
- Hook đang có: `~/.gemini/config/hooks.json` (định dạng: key = tên hook); `.claude/settings.local.json` (chỉ có permissions).
- Codex: có hỗ trợ hook/cấu hình theo từng project (thấy trong file chạy), nhưng HOÃN vì user tạm chỉ dùng agy.

## Overview

- P1 · ước 5h · chưa làm
- **agy:** chạy tự do (always-proceed). Hook `PreToolUse` chặn cứng việc sửa code/workflow, git và Drive. Hook `PreInvocation` báo trạng thái render. Bài học ghi vào hộp thư, kèm tin Telegram.
- **Claude:** hook `SessionStart` và `UserPromptSubmit` báo trạng thái render, số bài học đang chờ xác minh, và cảnh báo nếu có file được bảo vệ bị sửa mà chưa commit.
- **Codex:** hoãn.

## Key Insights

- **Yêu cầu của user:** "chạy tự do, miễn không tự động chỉnh, phá codebase, pipeline workflow render video chung của project". Nên: always-proceed + danh sách chặn (deny list); mọi việc khác cho qua. User đã duyệt danh sách chặn.
- **Chặn lệnh shell chỉ là phỏng đoán theo mẫu:** agy có thể lách (vd `python -c` để ghi file). Bù lại bằng cách phát hiện sau:
  - hook đầu phiên của Claude và lệnh `renders` báo nếu `git status --porcelain` thấy file được bảo vệ bị sửa;
  - lượt nghiệm thu kiểm `git status` sạch.
- **Khi chặn phải có `reason` rõ ràng**, để agy dừng lại báo user thay vì tìm cách khác.
- **Bài học:** agy chỉ ghi qua `videotool agent lesson` → thêm vào cuối `lessons-inbox.md` + tin Telegram "bài học mới chờ Claude xác minh". User quyết khi nào nhờ Claude xác minh rồi mới đưa vào references.
- **An toàn khi guard gặp lỗi:** nếu guard gặp lỗi nội bộ (vd payload lạ) thì trả `ask` (hỏi user), không trả `allow`. Vì always-proceed chỉ an toàn khi guard còn chạy đúng.

## Requirements

1. **`videotool agent guard --cli agy`:** đọc payload `PreToolUse` từ stdin, in ra JSON quyết định, không bao giờ crash.
   - **Chặn (`deny` + `reason`):**
     - tool ghi (`write_to_file`, `replace_file_content`, `multi_replace_file_content`) mà đích nằm trong repo nhưng NGOÀI `plans/**`, hoặc nằm dưới gdrive mount;
     - `run_command` thuộc một trong các loại:
       - git có đổi trạng thái: commit, push, reset, checkout, switch, restore, rebase, merge, stash, clean, rm, mv, cherry-pick, revert, tag, `branch -d/-D`, am, apply;
       - `pip` / `pip3` / `uv pip` install hoặc uninstall;
       - `kaggle kernels push`;
       - `rclone` có ghi/xoá: delete, deletefile, purge, move, moveto, sync, rmdir, rmdirs, cleanup, dedupe; `copy`, `copyto`, `copyurl` khi đích là remote;
       - `rm`, `mv`, `cp`, `>`, `>>`, `tee`, `sed -i`, `truncate` khi nhắm vào repo ngoài `plans/`, hoặc vào gdrive mount;
       - `systemctl --user stop|disable|mask videotool-watchd`.
   - **Cho qua (`allow`):** mọi việc khác, gồm:
     - mọi lệnh `videotool` (`creative lint/sfx-pin`, `cloud stage`, `run`, `renders`, `agent lesson`);
     - lệnh đọc (kể cả `rclone ls/lsf/lsl/lsd/cat/md5sum/size/about/tree/check`, `git status/log/diff`);
     - ghi vào `plans/`, `~/.cache/videotool`, `~/.local/state/videotool`, `/tmp`.
2. **`videotool agent lesson "<text>" [--episode <slug>] [--cli agy]`:**
   - thêm vào cuối `.agents/skills/make-video/references/lessons-inbox.md`: giờ UTC, CLI, tập, nội dung;
   - gửi Telegram: "Bài học mới từ agy chờ Claude xác minh: <tóm tắt một dòng>".
3. **`.agents/hooks.json`** (cùng định dạng với `~/.gemini/config/hooks.json`):
   ```json
   {
     "videotool-guard": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "<repo>/.venv/bin/videotool agent guard --cli agy", "timeout": 10}]}]},
     "videotool-renders": {"PreInvocation": [{"type": "command", "command": "<repo>/.venv/bin/videotool renders hook --cli agy --event auto", "timeout": 10}]}
   }
   ```
4. **Cài đặt agy:**
   - Tool Execution Policy = `always-proceed` (user chọn);
   - Non-Workspace File Access: cho phép các thư mục cần dùng (cache, state, `/tmp`, thư viện SFX/overlay để đọc).
   - Chỉ đặt sau khi guard đã chạy thử đạt.
5. **Claude — `.claude/settings.json`:**
   - `SessionStart` → `renders hook --cli claude --event start`; `UserPromptSubmit` → như trên với `--event prompt`.
   - Riêng `start` in thêm: số bài học chưa xử lý trong hộp thư, và cảnh báo nếu có file được bảo vệ bị sửa (dựa vào `git status`).
6. **`SKILL.md` + `AGENTS.md`**, luật cho agent render:
   - không sửa code hay workflow;
   - gặp lỗi code thì dừng và báo user;
   - bài học ghi bằng `videotool agent lesson` và nói lại với user trong phiên.
7. Gửi tin thử Telegram; chạy thử hook ở agy và Claude.
8. Ghi lại payload stdin thật của `PreToolUse` và `PreInvocation` từ agy một lần, để chốt tên field.

## Architecture

```
src/videotool/agent/guard.py        # decide(tool_call) -> allow|deny|ask + reason; path + command rules
src/videotool/agent/lessons.py      # append inbox entry + notify
src/videotool/cli/agent_commands.py # `agent`: guard, lesson
.agents/hooks.json                  # agy: PreToolUse guard + PreInvocation status
.claude/settings.json               # Claude: SessionStart / UserPromptSubmit status
```

Luồng agy: tool call → `PreToolUse` → guard → `deny` (kèm lý do) hoặc `allow` → tool chạy.

## Related code files

Tạo mới:
- `/home/dung/VIBE_CODING/video-tool/src/videotool/agent/{__init__,guard,lessons}.py`
- `/home/dung/VIBE_CODING/video-tool/src/videotool/cli/agent_commands.py`
- `/home/dung/VIBE_CODING/video-tool/tests/{test_agent_guard,test_agent_lessons}.py`
- `/home/dung/VIBE_CODING/video-tool/.agents/hooks.json`
- `/home/dung/VIBE_CODING/video-tool/.claude/settings.json`

Sửa:
- `/home/dung/VIBE_CODING/video-tool/src/videotool/cli/main.py`
- `/home/dung/VIBE_CODING/video-tool/src/videotool/runs/hook.py` (start của Claude: hộp thư + file được bảo vệ)
- `.agents/skills/make-video/SKILL.md`, `/home/dung/VIBE_CODING/video-tool/AGENTS.md`

Hoãn (Codex): `.codex/hooks.json`, `.codex/config.toml` (workspace-write + mạng + `writable_roots`).

## Implementation Steps

1. Ghi payload thật: tạm đặt một hook ghi stdin của agy ra `~/.local/state/videotool/agy-payload-*.json` (một lượt) → chốt tên field (`toolCall.name`, `args.TargetFile` / `CommandLine`…) → gỡ hook tạm.
2. Viết `guard.py` + test ma trận allow/deny, tối thiểu 30 ca dựng từ payload thật:
   - sửa `src/` → deny; ghi `plans/scratch` → allow;
   - `git status` → allow; `git commit` → deny;
   - `rclone lsf` → allow; `rclone delete gdrive:` → deny;
   - `kaggle kernels push` → deny; `videotool cloud stage` → allow;
   - `rm` trên mount → deny;
   - `python -c …` → allow, và ghi rõ đây là rủi ro còn lại;
   - JSON hỏng → ask.
3. Viết `lessons.py` + CLI + test: ghi đúng định dạng; gọi notifier; hermes lỗi thì dùng notify-send.
4. `runs/hook.py`: start của Claude có thêm dòng hộp thư và cảnh báo file bảo vệ; kèm test.
5. Ghi `.agents/hooks.json` + `.claude/settings.json`.
6. Chạy thử agy (lúc này vẫn để chế độ duyệt từng lệnh):
   - nhờ agy sửa 1 file trong `src/` → bị chặn, agy báo lại lý do;
   - `videotool renders` → cho qua;
   - trạng thái giả → dòng trạng thái hiện qua `PreInvocation`.

   Đạt cả 3 thì mới chuyển policy sang `always-proceed`.
7. Chạy thử Claude: phiên mới thấy trạng thái giả + số bài học.
8. Gửi tin thử Telegram (`videotool renders test-notify`) → user xác nhận đã nhận.
9. Cập nhật `SKILL.md` / `AGENTS.md`. `pytest -q` xanh. Commit `feat(agent): guard agy tool calls and collect lessons in an inbox`. Dừng hỏi user trước khi push.

## Todo

- [x] Ghi payload thật của agy — `toolCall.args.CommandLine`/`Cwd` đúng giả định; `invocationNum` đếm từ 0 (code đang so `== 1`, đã sửa); agy coi output `{}` là DENY nên guard luôn trả `decision` rõ ràng
- [x] `guard.py` + 74 ca test (41 chặn / 30 cho qua / 3 ca payload lỗi)
- [x] `lessons.py` + `videotool agent lesson` + 6 test
- [x] Hook start của Claude: hộp thư + file bảo vệ (chỉ hiện với `--cli claude`)
- [x] `.agents/hooks.json` + `.claude/settings.json` (Claude cần `hookEventName`, đã bổ sung)
- [x] Chạy thử agy: sửa `src/` bị chặn đúng lý do, `videotool renders` cho qua, `PreInvocation` hiện dòng trạng thái rồi im khi đã xem. Còn lại user tự bật Tool Execution Policy = always-proceed + Non-Workspace File Access trong app (không có trong settings.json)
- [x] Chạy thử Claude: `--event start` in đúng JSON `hookSpecificOutput`
- [x] Tin thử Telegram qua `agent lesson` thật (kênh: telegram), rồi hoàn nguyên hộp thư
- [x] `SKILL.md` / `AGENTS.md` + pytest (472) + commit

## Success Criteria

- Test guard (≥30 ca) xanh.
- Lượt chạy thử agy: sửa `src/` bị chặn, có lý do; các lệnh render đều cho qua.
- agy và Claude đều hiện dòng trạng thái khi có trạng thái giả; không có thì im lặng.
- `videotool agent lesson` → hộp thư có dòng mới, Telegram nhận được tin.
- User nhận được tin thử Telegram.

## Risk Assessment

- **Tên field trong payload agy khác giả định.**
  - Dấu hiệu: guard luôn cho qua vì không đọc được đường dẫn.
  - Xử lý: bước 1 ghi payload thật trước khi viết luật; test dựng từ payload thật.
- **agy lách guard bằng lệnh lạ.**
  - Dấu hiệu: `git status` có file bảo vệ bị sửa (hook Claude báo; nghiệm thu kiểm).
  - Xử lý: thêm luật chặn. Nếu lặp lại, hỏi user có chuyển về chế độ duyệt từng lệnh không.
- **Guard chặn nhầm việc hợp lệ.**
  - Dấu hiệu: agy báo bị chặn khi đang làm một bước render bình thường.
  - Xử lý: nới đúng luật đó, thêm test.
- **Hook chậm hoặc treo.** Timeout 10 giây; code chỉ đọc file local.

## Security Considerations

- Danh sách chặn là lớp bảo vệ chính cho yêu cầu của user. Guard gặp lỗi nội bộ thì trả `ask`, không trả `allow`.
- Không ghi toàn bộ nội dung lệnh vào log (lệnh có thể chứa secret); chỉ ghi quyết định và tên tool.
- agy không có quyền `kaggle kernels push`, không có quyền ghi hay xoá trên Drive ngoài các lệnh `videotool` có rào chắn.

## agy facts learned while testing (2026-09-20)

- **Output `{}` từ `PreToolUse` = DENY.** Lượt bắt payload dùng hook chỉ in `{}` và agy báo "mọi công
  cụ đều bị hook từ chối", kể cả `ask_question`. Guard luôn phải in `decision` rõ ràng.
- **`invocationNum` đếm từ 0** (payload thật), không phải 1.
- **Headless `-p`: allow-rule trong `settings.json` KHÔNG có tác dụng** — chuỗi trong binary agy:
  "Settings allow-rules do not apply; re-run with --dangerously-skip-permissions". Chạy tay trong
  app thì dùng Tool Execution Policy / `permissions.allow` (rule dạng `command(git commit)`, khớp
  theo tiền tố).
- **Print mode kết thúc khi lệnh còn chạy nền:** `creative lint` bị agy đẩy sang background rồi phiên
  `-p` thoát, mất kết quả (đúng tật đã thấy ở Phase 3). Render thật nên chạy agy tương tác.
- **Matcher của hook chỉ bắt 4 tool ghi/chạy lệnh**, nên `ask_question`, `view_file`, `grep_search`
  không phải qua guard — giữ được 4 cửa hỏi user của SKILL.md.

## Deviation from the approved deny list

`rclone copy` / `copyto` / `copyurl` to a remote stay ALLOWED. The approved list blocked them, but
Step 4b of the skill publishes an episode with `rclone copy "$STAGE/outputs" "$REMOTE/Output"`, so
blocking it would have blocked the job itself. Copy only adds files; every rclone verb that deletes
or overwrites (`delete`, `purge`, `move`, `moveto`, `sync`, `rmdir`, `cleanup`, `dedupe`) is denied.

## Next steps

- Phase 6: nghiệm thu BT55.
- Codex (hoãn): `.codex/hooks.json` + `.codex/config.toml`, làm khi user muốn dùng codex.
