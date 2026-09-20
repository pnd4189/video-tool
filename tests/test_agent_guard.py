"""The agy PreToolUse guard: what it blocks, what it must never block, and how it fails."""

from __future__ import annotations

from pathlib import Path

import pytest

from videotool.agent import guard

REPO = guard.REPO_ROOT
MOUNT = "/home/dung/cloud/gdrive"
STAGE = "/home/dung/.cache/videotool/Chap 55"


def _write(target: str, tool: str = "write_to_file") -> dict:
    return {"toolCall": {"name": tool, "args": {"TargetFile": target}}}


def _cmd(command: str, cwd: str = str(REPO)) -> dict:
    return {"toolCall": {"name": "run_command", "args": {"CommandLine": command, "Cwd": cwd}}}


DENIED = [
    ("edit the job spec", _write(f"{REPO}/src/videotool/core/job_spec.py")),
    ("edit a test", _write(f"{REPO}/tests/test_cloud_stage.py")),
    ("edit the skill", _write(f"{REPO}/.agents/skills/make-video/SKILL.md")),
    ("edit its own hook config", _write(f"{REPO}/.agents/hooks.json")),
    ("edit AGENTS.md", _write(f"{REPO}/AGENTS.md")),
    ("edit the notebook", _write(f"{REPO}/Colab/videotool-render.ipynb")),
    ("patch code", _write(f"{REPO}/src/videotool/render/executor.py", "replace_file_content")),
    ("multi-patch code", _write(f"{REPO}/src/videotool/cli/main.py", "multi_replace_file_content")),
    ("write on the mount", _write(f"{MOUNT}/1. YOUTUBE AUDIO/Chap 55/job.yaml")),
    ("relative path into src", _write("src/videotool/core/services.py")),
    ("git commit", _cmd("git commit -m 'fix'")),
    ("git push", _cmd("git push origin main")),
    ("git reset --hard", _cmd("git reset --hard origin/main")),
    ("git checkout a file", _cmd("git checkout -- src/videotool/cli/main.py")),
    ("git clean", _cmd("git clean -fd")),
    ("git stash", _cmd("git stash")),
    ("git branch -D", _cmd("git branch -D feat/x")),
    ("git commit behind -C", _cmd(f"git -C {REPO} commit --amend")),
    ("git commit after a cd", _cmd("cd /home/dung && git add -A && git commit -m x")),
    ("pip install", _cmd(".venv/bin/pip install faster-whisper")),
    ("pip uninstall", _cmd("pip3 uninstall videotool")),
    ("python -m pip install", _cmd("python -m pip install torch")),
    ("uv pip install", _cmd("uv pip install numpy")),
    ("kaggle kernels push", _cmd("kaggle kernels push -p Colab")),
    ("rclone delete", _cmd("rclone delete gdrive:_VIDEOTOOL_SHARED/render_job.json")),
    ("rclone purge", _cmd("rclone purge gdrive:x")),
    ("rclone sync", _cmd(f"rclone sync {STAGE}/outputs gdrive:ep/Output")),
    ("rclone moveto", _cmd("rclone moveto gdrive:a gdrive:b")),
    ("rclone copy INTO the mount", _cmd(f"rclone copy {STAGE} '{MOUNT}/1. YOUTUBE AUDIO/Chap 55'")),
    ("rm inside the repo", _cmd(f"rm -rf {REPO}/src/videotool/cloud")),
    ("rm on the mount", _cmd(f"rm '{MOUNT}/1. YOUTUBE AUDIO/Chap 55/voice.wav'")),
    ("mv a repo file away", _cmd("mv src/videotool/cli/main.py /tmp/main.py")),
    ("cp over a repo file", _cmd("cp /tmp/main.py src/videotool/cli/main.py")),
    ("sed -i on code", _cmd("sed -i 's/a/b/' src/videotool/creative/rules.py")),
    ("truncate a test", _cmd("truncate -s 0 tests/test_run_state.py")),
    ("redirect into code", _cmd("echo x > src/videotool/x.py")),
    ("attached redirect into code", _cmd("echo x >src/videotool/x.py")),
    ("append into AGENTS.md", _cmd("echo rule >> AGENTS.md")),
    ("tee into the skill", _cmd("echo x | tee .agents/skills/make-video/SKILL.md")),
    ("stop the watcher", _cmd("systemctl --user stop videotool-watchd")),
    ("disable the watcher", _cmd("systemctl --user disable videotool-watchd.service")),
]

ALLOWED = [
    ("author the creative", _write(f"{REPO}/plans/scratch-chap55/creative.yaml")),
    ("write picks", _write(f"{REPO}/plans/scratch-chap55/picks.yaml")),
    ("write a report", _write(f"{REPO}/plans/reports/agy-260920-render.md")),
    ("edit the staged job", _write(f"{STAGE}/job.yaml")),
    ("write into /tmp", _write("/tmp/notes.txt")),
    ("write the render state", _write("/home/dung/.local/state/videotool/renders/x.json")),
    ("read tools pass", {"toolCall": {"name": "view_file", "args": {"TargetFile": f"{REPO}/AGENTS.md"}}}),
    ("grep passes", {"toolCall": {"name": "grep_search", "args": {"Query": "sfx"}}}),
    ("git status", _cmd("git status --porcelain")),
    ("git log", _cmd("git log --oneline -5")),
    ("git diff", _cmd("git diff -- src")),
    ("creative lint", _cmd(".venv/bin/videotool creative lint gdrive:x --creative c.yaml")),
    ("sfx-pin", _cmd(".venv/bin/videotool creative sfx-pin gdrive:x --picks p.yaml --creative c.yaml")),
    ("cloud stage", _cmd(".venv/bin/videotool cloud stage gdrive:x --creative c.yaml --runtime tpu")),
    ("renders", _cmd(".venv/bin/videotool renders")),
    ("agent lesson", _cmd('.venv/bin/videotool agent lesson "x" --episode binh-thien-chap55')),
    ("local render", _cmd(f'.venv/bin/videotool render "{STAGE}/job.yaml" --preset youtube-16x9')),
    ("rclone lsf", _cmd("rclone lsf gdrive:x --fast-list")),
    ("rclone cat", _cmd("rclone cat gdrive:x/job.yaml")),
    ("stage from the mount", _cmd(f'rclone copy "gdrive:1. YOUTUBE AUDIO/Chap 55" "{STAGE}" --transfers 8')),
    ("publish the outputs", _cmd(f'rclone copy "{STAGE}/outputs" "gdrive:1. YOUTUBE AUDIO/Chap 55/Output"')),
    ("kaggle kernels status", _cmd("kaggle kernels status pnd4189/videotool-render-tpu")),
    ("kaggle kernels output", _cmd("kaggle kernels output pnd4189/videotool-render -p /tmp/log")),
    ("copy the srt into the stage", _cmd(f'cp "{STAGE}"/x_vi_qa.srt "{STAGE}/outputs/captions.srt"')),
    ("delete only the stage", _cmd(f'rm -rf "{STAGE}"')),
    ("write scratch through a pipe", _cmd("echo x > plans/scratch-chap55/notes.md")),
    ("ffprobe the output", _cmd(f'ffprobe -v error "{STAGE}/outputs/x.mp4"')),
    ("run the watcher once", _cmd(".venv/bin/videotool cloud watchd --once")),
    ("python -c is a known hole", _cmd("python -c 'print(1)'")),
    ("systemctl status", _cmd("systemctl --user status videotool-watchd")),
]


@pytest.mark.parametrize("name,payload", DENIED, ids=[n for n, _ in DENIED])
def test_denied_with_a_reason(name: str, payload: dict) -> None:
    result = guard.decide(payload)
    assert result["decision"] == "deny", name
    assert len(result.get("reason", "")) > 20, f"{name}: the reason must tell agy what to do instead"


@pytest.mark.parametrize("name,payload", ALLOWED, ids=[n for n, _ in ALLOWED])
def test_allowed(name: str, payload: dict) -> None:
    assert guard.decide(payload)["decision"] == "allow", name


def test_a_payload_it_cannot_read_asks_instead_of_allowing() -> None:
    for payload in ({}, {"toolCall": "nope"}, {"toolCall": {"name": "write_to_file", "args": {}}},
                    {"toolCall": {"name": "run_command", "args": {"CommandLine": None}}}):
        assert guard.decide(payload)["decision"] == "ask", payload


def test_the_mount_location_follows_the_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VIDEOTOOL_GDRIVE_MOUNT", str(tmp_path / "mnt"))
    assert guard.decide(_write(str(tmp_path / "mnt/ep/job.yaml")))["decision"] == "deny"
    assert guard.decide(_write(f"{MOUNT}/ep/job.yaml"))["decision"] == "allow"  # no longer the mount


def test_the_module_entry_point_never_fails(capsys, monkeypatch) -> None:
    import io
    import json

    monkeypatch.setattr("sys.stdin", io.StringIO("not json at all"))
    assert guard.main() == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "ask"
