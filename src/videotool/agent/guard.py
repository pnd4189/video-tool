"""Decide one agy `PreToolUse` call: block edits to this pipeline, allow the render work.

The user's rule is "run freely, just do not touch the shared codebase / render workflow", so this
is a narrow deny list and everything else passes. Payload shape (from agy, verified against the
visual-prompt guard running on this machine): `{"toolCall": {"name", "args"}, …}`, write tools
carry `args.TargetFile`, `run_command` carries `args.CommandLine` + `args.Cwd`. The answer is
`{"decision": "allow"|"deny"|"ask", "reason"?}` on stdout.

Shell matching is pattern-based, so a determined agent can still write through `python -c`. That
residual risk is covered after the fact: Claude's session hook and `videotool renders` report a
protected file that shows up modified in `git status`.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path, PurePosixPath

WRITE_TOOLS = ("write_to_file", "replace_file_content", "multi_replace_file_content")
REPO_ROOT = Path(__file__).resolve().parents[3]
WRITABLE_IN_REPO = ("plans",)  # the agent's own scratch folders live here
DEFAULT_MOUNT = "/home/dung/cloud/gdrive"

# git subcommands that change the working tree, the index or a remote.
GIT_DENY = {"commit", "push", "reset", "checkout", "switch", "restore", "rebase", "merge", "stash",
            "clean", "rm", "mv", "cherry-pick", "revert", "tag", "am", "apply"}
GIT_GLOBAL_WITH_VALUE = ("-C", "--git-dir", "--work-tree", "--namespace", "-c")
# rclone subcommands that delete or overwrite. `copy`/`copyto`/`copyurl` pass when they write to a
# local folder or into an episode's outputs/ (how the local flow publishes); see _rclone_denial.
RCLONE_DENY = {"delete", "deletefile", "purge", "move", "moveto", "sync", "rmdir", "rmdirs",
               "cleanup", "dedupe"}
WATCHD_DENY = {"stop", "disable", "mask", "kill"}
# Commands whose every path argument is destroyed or overwritten, and those where only the last is.
FS_ALL_ARGS = {"rm", "rmdir", "shred", "truncate", "tee", "unlink"}
FS_LAST_ARG = {"cp", "install", "ln"}
SEGMENT_SPLIT = re.compile(r"(?:&&|\|\||[;\n|])")
REMOTE_SPEC = re.compile(r"^[A-Za-z0-9_.-]+(?:,[^:]*)?:")


def mount() -> Path:
    return Path(os.environ.get("VIDEOTOOL_GDRIVE_MOUNT", DEFAULT_MOUNT))


def _resolve(raw: str, cwd: Path) -> Path:
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else cwd / path).resolve()


def write_denial(path: Path) -> str | None:
    """Why this path may not be written, or None when it is fair game."""
    if path.is_relative_to(mount()):
        return (f"{path} nằm trong thư mục gdrive đã mount — đó là tư liệu gốc, chỉ đọc. Stage bằng "
                "`rclone copy` vào $HOME/.cache/videotool/<tên> rồi làm việc ở đó.")
    if path.is_relative_to(REPO_ROOT):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts and rel.parts[0] in WRITABLE_IN_REPO:
            return None
        return (f"{rel} là code/workflow chung của project — agent render không được sửa. Nếu thấy "
                "code sai thì dừng lại và báo user; bài học thì ghi bằng `videotool agent lesson`. "
                "Thư mục làm việc của bạn là plans/scratch-<slug>/.")
    return None


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _looks_like_path(raw: str, cwd: Path) -> bool:
    """A flag's value is not a path: `--transfers 8` must not read as writing `./8`."""
    if not raw or raw.startswith("-") or "=" in raw or raw.isdigit():
        return False
    return "/" in raw or raw.startswith("~") or "." in Path(raw).name or _resolve(raw, cwd).exists()


def _paths_after(tokens: list[str], skip: int, cwd: Path) -> list[Path]:
    """Path arguments of a shell command, flags and their values dropped."""
    return [_resolve(t, cwd) for t in tokens[skip:] if _looks_like_path(t, cwd)]


def _git_denial(tokens: list[str]) -> str | None:
    rest = tokens[1:]
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in GIT_GLOBAL_WITH_VALUE else rest[1:]
    if not rest:
        return None
    sub, flags = rest[0], set(rest[1:])
    if sub in GIT_DENY:
        return f"`git {sub}` đổi trạng thái repo — agent render không chạy git ghi. Báo user để Claude làm."
    if sub == "branch" and flags & {"-d", "-D", "-m", "-M", "--delete", "--move"}:
        return "`git branch` xoá/đổi tên nhánh — không chạy. Báo user."
    return None


def _pip_denial(tokens: list[str]) -> str | None:
    name = Path(tokens[0]).name
    rest = tokens[1:]
    if name in ("uv", "uvx") and rest[:1] == ["pip"]:
        rest = rest[1:]
    elif name.startswith("python") and rest[:2] == ["-m", "pip"]:
        rest = rest[2:]
    elif not name.startswith("pip"):
        return None
    if {"install", "uninstall"} & set(rest):
        return ("cài/xoá package sẽ đổi môi trường chung của project — không chạy. Thiếu thư viện thì "
                "báo user.")
    return None


def _rclone_denial(tokens: list[str], cwd: Path) -> str | None:
    rest = [t for t in tokens[1:] if not t.startswith("-")]
    if not rest:
        return None
    if rest[0] in RCLONE_DENY:
        return (f"`rclone {rest[0]}` xoá hoặc ghi đè ở đích — Drive và mount là tư liệu gốc. Chỉ dùng "
                "`rclone copy`/`copyto` (chỉ thêm file) hoặc các lệnh đọc.")
    if rest[0] in ("copy", "copyto", "copyurl"):
        paths = [t for t in rest[1:] if REMOTE_SPEC.match(t) or _looks_like_path(t, cwd)]
        dest = paths[-1] if len(paths) >= 2 else None  # the destination is the last path argument
        if dest is None:
            return None
        if REMOTE_SPEC.match(dest):
            # Copy only adds files, but onto an existing name it overwrites: agy replaced an
            # episode's source template this way (ĐS22). Publishing is the one remote write it makes.
            where = PurePosixPath(dest.split(":", 1)[1])
            if ".." in where.parts or not {"outputs", "Output"} & set(where.parts):
                return (f"`rclone {rest[0]}` ghi lên Drive ngoài outputs/ ({dest}) — tư liệu gốc và "
                        "_VIDEOTOOL_SHARED không phải chỗ agent ghi. Publish vào <tập>/outputs hoặc "
                        "<tập>/Output; cần ghi chỗ khác thì dừng lại hỏi user.")
            return None
        return write_denial(_resolve(dest, cwd))
    return None


def _kaggle_denial(tokens: list[str]) -> str | None:
    rest = [t for t in tokens[1:] if not t.startswith("-")]
    if rest[:2] == ["kernels", "push"]:
        return ("`kaggle kernels push` ghi đè notebook trên Kaggle — chỉ user làm. Bạn chỉ cần "
                "`videotool cloud stage`, rồi nhắc user bấm Save & Run All.")
    return None


def _systemctl_denial(tokens: list[str]) -> str | None:
    rest = set(tokens[1:])
    if rest & WATCHD_DENY and any("videotool-watchd" in t for t in tokens):
        return "videotool-watchd là bộ canh render của user — không dừng/tắt nó."
    return None


def _redirect_denial(tokens: list[str], cwd: Path) -> str | None:
    """`> path`, `>>path`, `2>path` — the shell writes it whatever the command is."""
    for i, token in enumerate(tokens):
        m = re.match(r"^\d?>>?(.*)$", token)
        if not m:
            continue
        raw = m.group(1) or (tokens[i + 1] if i + 1 < len(tokens) else "")
        if not raw:
            continue
        reason = write_denial(_resolve(raw, cwd))
        if reason:
            return f"ghi tràn vào chỗ được bảo vệ: {reason}"
    return None


def _fs_denial(tokens: list[str], cwd: Path) -> str | None:
    name = Path(tokens[0]).name
    if name == "sed":
        if not any(t.startswith("-i") or t == "--in-place" for t in tokens[1:]):
            return None
        paths = _paths_after(tokens, 1, cwd)[1:]  # the first non-flag token is the sed script
    elif name == "mv":
        paths = _paths_after(tokens, 1, cwd)  # both sides move: the source stops existing
    elif name in FS_ALL_ARGS:
        paths = _paths_after(tokens, 1, cwd)
    elif name in FS_LAST_ARG:
        paths = _paths_after(tokens, 1, cwd)[-1:]
    else:
        return None
    for path in paths:
        reason = write_denial(path)
        if reason:
            return f"`{name}` vào chỗ được bảo vệ: {reason}"
    return None


def command_denial(command: str, cwd: Path) -> str | None:
    """The first reason to refuse this shell command, or None to let it run."""
    for segment in SEGMENT_SPLIT.split(command):
        tokens = _tokens(segment.strip())
        if not tokens:
            continue
        reason = _redirect_denial(tokens, cwd)
        if reason:
            return reason
        while tokens and (tokens[0] in ("sudo", "env", "nohup", "time", "command") or "=" in tokens[0]):
            tokens = tokens[1:]
        if not tokens:
            continue
        name = Path(tokens[0]).name
        checks = {"git": _git_denial, "kaggle": _kaggle_denial, "systemctl": _systemctl_denial}
        if name in checks:
            reason = checks[name](tokens)
        elif name == "rclone":
            reason = _rclone_denial(tokens, cwd)
        else:
            reason = _pip_denial(tokens) or _fs_denial(tokens, cwd)
        if reason:
            return reason
    return None



def decide(payload: dict) -> dict:
    """`{"decision": …}` for one PreToolUse payload. Unknown shapes ask instead of allowing."""
    call = payload.get("toolCall")
    if not isinstance(call, dict):
        return {"decision": "ask", "reason": "videotool guard: không đọc được toolCall trong payload"}
    tool, args = call.get("name"), call.get("args")
    if not isinstance(args, dict):
        args = {}
    if tool in WRITE_TOOLS:
        raw = args.get("TargetFile")
        if not isinstance(raw, str) or not raw.strip():
            return {"decision": "ask", "reason": "videotool guard: tool ghi mà không thấy TargetFile"}
        reason = write_denial(_resolve(raw, Path(args.get("Cwd") or REPO_ROOT)))
        return {"decision": "deny", "reason": reason} if reason else {"decision": "allow"}
    if tool == "run_command":
        command = args.get("CommandLine")
        if not isinstance(command, str):
            return {"decision": "ask", "reason": "videotool guard: run_command mà không thấy CommandLine"}
        reason = command_denial(command, Path(args.get("Cwd") or REPO_ROOT).expanduser())
        return {"decision": "deny", "reason": reason} if reason else {"decision": "allow"}
    return {"decision": "allow"}


def main(argv: list[str] | None = None) -> int:
    """Lightweight entry point for the agy hook: `python -m videotool.agent.guard`.

    PreToolUse fires on every tool call, so this skips the Typer CLI's pydantic import (~180ms).
    Always exits 0; anything unexpected asks the user rather than allowing."""
    import json
    import sys

    try:
        decision = decide(json.load(sys.stdin))
    except BaseException as exc:  # noqa: BLE001 — a broken guard must not open the door
        decision = {"decision": "ask",
                    "reason": f"videotool guard lỗi ({type(exc).__name__}) — hỏi user trước khi chạy tool này"}
    print(json.dumps(decision, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
