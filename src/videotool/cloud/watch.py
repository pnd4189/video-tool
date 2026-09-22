"""The watcher state machine: one `step()` per active render per poll, plus the daemon loop.

staged --(new QUEUED/RUNNING)--> queued/running --COMPLETE--> verifying --> done|failed
Every notification goes through `notify()` exactly once per event name, so a daemon restart
never repeats a message. Network failures back off and eventually park the render in
watch-error (still retried) instead of killing the daemon.
"""

from __future__ import annotations

import json
import subprocess
import time

import yaml

from videotool.cloud import remote
from videotool.cloud.remote import Runner
from videotool.cloud.config import ABANDON_AFTER_S, POLL_S, PROGRESS_S, REMIND_AFTER_S, config_name, shared_root
from videotool.cloud.finish import RefuseCleanup, _read_config, finish
from videotool.cloud.kernel_log import kernel_error_lines
from videotool.cloud.stage_guards import slug_of
from videotool.cloud.verify import verify_output
from videotool.runs import state as run_state
from videotool.runs.notify import notify, send

MAX_FAILURES = 3


def step(state: dict, runner: Runner, now: float | None = None) -> dict:
    """Advance one render by one poll. Never raises for a single render's trouble."""
    now = now if now is not None else time.time()
    try:
        _step(state, runner, now, shared_root())
    except (remote.RemoteError, subprocess.SubprocessError, TimeoutError, OSError, ValueError) as exc:
        state["failures"] = int(state.get("failures", 0)) + 1
        state["error"] = str(exc)[:300]
        if state["failures"] >= MAX_FAILURES and state.get("status") != "watch-error":
            run_state.transition(state, "watch-error", state["error"])
            notify(runner, state, "watch-error", f"[{state['slug']}] watch lỗi: {state['error']}")
        run_state.save(state)
    return state


def _step(state: dict, runner: Runner, now: float, shared: str) -> None:
    status = state.get("status")
    if status == "staged":
        _staged(state, runner, now)
    elif status in ("queued", "running"):
        _live(state, runner, now, shared)
    elif status == "verifying":
        _verify(state, runner, shared)
    elif status == "watch-error":
        state["failures"] = 0
        _step_back(state, runner, now, shared)
    run_state.save(state)


def _step_back(state: dict, runner: Runner, now: float, shared: str) -> None:
    """Recovered from watch-errors: resume from wherever the history left the render."""
    previous = (state.get("history") or [{}])[-1].get("from") or "staged"
    run_state.transition(state, previous, "hồi phục sau watch-error")
    _step(state, runner, now, shared)


def _unknown_status(state: dict, runner: Runner, status: str | None) -> bool:
    """An unreadable kernel status is a watch failure: park after 3 in a row (unknown parser?)."""
    if status is not None:
        state["failures"] = 0
        return False
    state["failures"] = int(state.get("failures", 0)) + 1
    if state["failures"] >= MAX_FAILURES and state.get("status") != "watch-error":
        run_state.transition(state, "watch-error", "kernel status không đọc được 3 lần liền")
        notify(runner, state, "watch-error",
               f"[{state['slug']}] không đọc được trạng thái kernel 3 lần — kiểm tra kaggle CLI")
    return True


def _staged(state: dict, runner: Runner, now: float) -> None:
    waited = now - float(state.get("staged_at") or now)
    kernel_status = remote.kernel_status(runner, state["kernel"])
    if _unknown_status(state, runner, kernel_status):
        return
    if kernel_status in ("queued", "running"):
        run_state.transition(state, "running" if kernel_status == "running" else "queued")
        # One "started" per run, so the wording must match what Kaggle actually reports now: a
        # queued kernel has been accepted, not started, and no second message follows.
        moved = "bắt đầu chạy" if kernel_status == "running" else "đã vào hàng đợi"
        notify(runner, state, "started", f"[{state['slug']}] {moved} trên Kaggle "
                                         f"(chờ {waited/60:.0f} phút) — {state['kernel']}")
        return
    if waited >= ABANDON_AFTER_S:
        run_state.transition(state, "abandoned", "24h không ai bấm chạy")
        notify(runner, state, "abandoned", f"[{state['slug']}] 24 giờ chưa được chạy — bỏ canh")
    elif waited >= REMIND_AFTER_S:
        notify(runner, state, "remind",
               f"[{state['slug']}] đã stage {waited/60:.0f} phút, chưa thấy chạy — nhớ bấm Save & Run All")


def _live(state: dict, runner: Runner, now: float, shared: str) -> None:
    kernel_status = remote.kernel_status(runner, state["kernel"])
    if _unknown_status(state, runner, kernel_status):
        return
    if kernel_status == "complete":
        run_state.transition(state, "verifying")
        _verify(state, runner, shared)
        return
    if kernel_status == "queued" and state["status"] == "running":
        run_state.transition(state, "queued", "quay lại hàng đợi")
    if kernel_status in ("error", "cancelled"):
        _failed(state, runner, kernel_status)
        return
    if kernel_status == "running" and run_state.transition(state, "running"):
        notify(runner, state, "started",
               f"[{state['slug']}] bắt đầu chạy trên Kaggle — {state['kernel']}")

    progress = state.get("progress") or {}
    if now - float(progress.get("at") or 0) >= PROGRESS_S:
        clips = remote.count_clips(runner, state["checkpoint"])
        state["progress"] = {"clips": clips, "at": now}
        if clips >= 0:
            print(f"[{state['slug']}] {clips} clip")
    _early_check(state, runner, shared)


def _early_check(state: dict, runner: Runner, shared: str) -> None:
    """Once the checkpoint job.yaml lands, sanity-check the creative wiring it carries."""
    if state.get("early_check"):
        return
    try:
        job = remote.remote_text(runner, f"{state['checkpoint']}/job.yaml", 120)
    except remote.RemoteError:
        return
    data = yaml.safe_load(job) or {}
    inputs = data.get("inputs") or {}
    notes = []
    if not inputs.get("music"):
        notes.append("thiếu inputs.music — bed sẽ bị bỏ")
    for key in ("intro_cta", "outro_cta", "intro_image", "ending_image", "description_template"):
        if not inputs.get(key):
            notes.append(f"thiếu inputs.{key}")
    sfx = len(((data.get("enhance") or {}).get("sfx") or {}).get("cues") or [])
    music = len((data.get("audio") or {}).get("music_schedule") or [])
    state["early_check"] = {
        "timing": (data.get("timing") or {}).get("source"),
        "scenes": len(data.get("storyboard") or []),
        "sfx": sfx, "music": music,
        "encoder": (data.get("render") or {}).get("encoder"),
    }
    if notes:
        notify(runner, state, "early-check",
               f"[{state['slug']}] early-check BẤT THƯỜNG: " + "; ".join(notes))
    else:
        print(f"[{state['slug']}] early-check OK "
              f"(timing={state['early_check']['timing']}, scenes={state['early_check']['scenes']})")


def _verify(state: dict, runner: Runner, shared: str) -> None:
    result = verify_output(runner, state)
    state["verify"] = result
    if result["ok"]:
        run_state.transition(state, "done", "verify ĐẠT")
        state.pop("error", None)  # a finished render must not keep showing an old watch hiccup
        try:
            finish(runner, state, shared)
            note = "config đã dọn"
        except RefuseCleanup as exc:
            note = f"giữ config: {exc}"
        size_gb = max(0, int(state.get("mp4_bytes") or 0)) / 1e9
        notify(runner, state, "done",
               f"[{state['slug']}] XONG ✔ {state.get('mp4', '')} ({size_gb:.2f} GB) · verify ĐẠT · {note}")
    else:
        run_state.transition(state, "failed", "; ".join(result["findings"])[:200])
        notify(runner, state, "failed",
               f"[{state['slug']}] xong nhưng VERIFY LỖI: " + " | ".join(result["findings"])[:500]
               + " — config giữ nguyên")


def _failed(state: dict, runner: Runner, kind: str) -> None:
    lines = kernel_error_lines(runner, state["kernel"])
    state["error"] = " / ".join(lines)[:400]
    run_state.transition(state, "failed", kind)
    notify(runner, state, "failed",
           f"[{state['slug']}] kernel {kind.upper()} — config giữ nguyên: " + " / ".join(lines)[:400])


def _warn_orphan_configs(runner: Runner, shared: str) -> list[str]:
    """Warn once per slug about a runtime config on Drive with no state file — a render nobody is
    watching. CHAP 3 was hand-staged by a script and failed on Kaggle twice before anyone noticed,
    exactly because no state meant no watcher and no notification."""
    marker = run_state.state_dir() / ".orphan-warned.json"
    try:
        warned = set(json.loads(marker.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        warned = set()
    fresh: list[str] = []
    for runtime in ("gpu", "tpu"):
        config = _read_config(runner, f"{shared}/{config_name(runtime)}")
        slug = slug_of(config) if config else ""
        if not slug or slug in warned or run_state.load(slug) is not None:
            continue
        warned.add(slug)
        fresh.append(slug)
        send(runner, f"[videotool] {config_name(runtime)} trỏ {slug} nhưng KHÔNG có state — render này "
                     "không được canh (stage tay?). Chạy lại `videotool cloud stage` cho đúng luồng, hoặc "
                     f"`videotool cloud finish {slug}` để dọn.")
    if fresh:
        try:
            run_state.ensure_dir()
            marker.write_text(json.dumps(sorted(warned)), encoding="utf-8")
        except OSError:
            pass
    return fresh


def loop(runner: Runner = remote.real_runner, once: bool = False) -> None:
    """The daemon body: poll every active state file; one bad render never stops the rest."""
    last_orphan = 0.0
    while True:
        if time.time() - last_orphan >= PROGRESS_S:  # also fires on the first pass (--once included)
            last_orphan = time.time()
            try:
                for slug in _warn_orphan_configs(runner, shared_root()):
                    print(f"[{slug}] config trên Drive không có state — đã báo")
            except Exception as exc:  # noqa: BLE001 — the daemon must survive anything
                print(f"[orphan-check] crash: {exc}")
        for state in run_state.list_states(days=30):
            try:
                step(state, runner)
            except Exception as exc:  # noqa: BLE001 — the daemon must survive anything
                print(f"[{state.get('slug')}] step crash: {exc}")
        if once:
            return
        time.sleep(POLL_S)
