"""The watcher state machine: transitions, notifications once, verify paths, error parsing."""

from __future__ import annotations

import json

from videotool.cloud import watch as watch_mod
from videotool.runs import state as run_state

from cloud_fakes import FakeRunner  # noqa: TID252

SHARED = "gdrive:_VIDEOTOOL_SHARED"
RUNNING = 'k has status "KernelWorkerStatus.RUNNING"'
QUEUED = 'k has status "KernelWorkerStatus.QUEUED"'
COMPLETE = 'k has status "KernelWorkerStatus.COMPLETE"'
ERROR = 'k has status "KernelWorkerStatus.ERROR"'
FILES_OK = ["Tập 1.mp4", "quality-report.json", "description.txt", "captions.youtube.srt",
            "thumbnail-1280x720.jpg"]
QA_OK = [{"name": "loudness_lufs", "status": "pass", "message": "-13.7 LUFS"}]
# mvhd duration 100s; the state's expectation is set to 100 too.
MP4_HEAD = (b"\x00\x00\x00\x20ftypisom" + b"\x00\x00\x01\x08moov"
            + b"\x00\x00\x00\x6Cmvhd" + b"\x00" * 12
            + b"\x00\x00\x03\xe8\x00\x01\x86\xa0" + b"\x00" * 76).decode("latin-1")


def _state(tmp_path):
    st = run_state.new("s", kernel="k", config_name="render_job.json",
                       checkpoint=f"{SHARED}/checkpoints/s", output="gdrive:out",
                       title="Tập 1", expected_seconds=100.0, intro_cta_seconds=8.7, staged_at=1000.0)
    run_state.save(st)
    return st


def _runner(kernel=RUNNING, clips="scene-0001.mp4\nscene-0002.mp4\n", job_yaml=None,
            listing=FILES_OK, qa=QA_OK):
    responses = {
        ("kaggle", "kernels", "status"): (0, kernel),
        ("rclone", "lsf"): (0, clips),
        ("hermes", "send"): (0, ""),
    }

    class R(FakeRunner):
        def __call__(self, args, timeout=0, env=None):
            super().__call__(args, timeout=timeout, env=env)
            joined = " ".join(args)
            if args[:2] == ["rclone", "lsf"] and "clips" in joined:
                return 0, clips.encode()
            if args[:2] == ["rclone", "lsf"]:
                return 0, "\n".join(f"1000\t{name}" for name in listing).encode()
            if args[:2] == ["rclone", "cat"] and "job.yaml" in joined:
                return (0, job_yaml.encode()) if job_yaml else (1, b"")
            if "quality-report.json" in joined:
                return 0, json.dumps(qa).encode()
            if "description.txt" in joined:
                return 0, "Mô tả.\n==== TAGS ====\nx".encode("utf-8")
            if "--head" in joined:
                return 0, MP4_HEAD.encode("latin-1")
            for prefix in sorted(self.responses, key=len, reverse=True):
                if tuple(args[: len(prefix)]) == prefix:
                    code, out = self.responses[prefix]
                    return code, self._bytes(out)
            return 0, b""

    return R(responses)


def test_staged_ignores_a_stale_complete_and_starts_on_running(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    watch_mod.step(st, _runner(kernel=COMPLETE), now=1100.0)
    assert st["status"] == "staged" and not st.get("last_event")
    watch_mod.step(st, _runner(kernel=RUNNING), now=1100.0)
    assert st["status"] == "running" and st["last_event"]["event"] == "started"


def test_staged_reminds_once_then_abandons(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    runner = _runner(kernel=COMPLETE)
    watch_mod.step(st, runner, now=1000.0 + 3601.0)
    assert st.get("last_event", {}).get("event") == "remind"
    watch_mod.step(st, runner, now=1000.0 + 4000.0)
    assert st["last_event"]["event"] == "remind"  # still just the one reminder
    watch_mod.step(st, runner, now=1000.0 + 86401.0)
    assert st["status"] == "abandoned"


def test_running_counts_clips_and_early_checks_the_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    run_state.transition(st, "running")
    job = "inputs: {music: Music, intro_cta: x.mp4, outro_cta: y.mp4, intro_image: a.jpg, " \
          "ending_image: b.jpg, description_template: t.txt}\nstoryboard: [{}, {}]\n" \
          "enhance: {sfx: {cues: [{}, {}]}, parallax: false}\naudio: {music_schedule: [{}, {}]}\n" \
          "timing: {source: anchor}\nrender: {encoder: libx264-balanced-capped-2500k}\n"
    runner = _runner(job_yaml=job)
    watch_mod.step(st, runner, now=2000.0)
    assert st["progress"]["clips"] == 2
    assert st["early_check"] == {"timing": "anchor", "scenes": 2, "sfx": 2, "music": 2,
                                 "encoder": "libx264-balanced-capped-2500k"}
    assert not st.get("last_event")  # healthy early check is silent


def test_early_check_flags_missing_wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    run_state.transition(st, "running")
    runner = _runner(job_yaml="inputs: {}\n")  # nothing wired
    watch_mod.step(st, runner, now=2000.0)
    assert st["last_event"]["event"] == "early-check"
    assert "inputs.music" in st["last_event"]["detail"]


def test_complete_verifies_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    run_state.transition(st, "running")
    runner = _runner(kernel=COMPLETE)
    runner.responses[("rclone", "cat", f"{SHARED}/render_job.json")] = \
        (0, json.dumps({"checkpoint": f"{SHARED}/checkpoints/s"}))
    watch_mod.step(st, runner, now=3000.0)
    assert st["status"] == "done" and st["verify"]["ok"]
    assert runner.seen("rclone", "delete", f"{SHARED}/render_job.json")
    assert st["last_event"]["event"] == "done"


def test_verify_failure_keeps_the_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    st["expected_seconds"] = 999.0  # duration mismatch incoming
    run_state.transition(st, "running")
    runner = _runner(kernel=COMPLETE)
    watch_mod.step(st, runner, now=3000.0)
    assert st["status"] == "failed" and any("độ dài" in f for f in st["verify"]["findings"])
    assert not runner.seen("rclone", "delete")


def test_kernel_error_parks_failed_with_log_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    run_state.transition(st, "running")
    runner = _runner(kernel=ERROR)
    watch_mod.step(st, runner, now=3000.0)
    assert st["status"] == "failed"
    assert runner.seen("kaggle", "kernels", "output")


def test_error_lines_read_the_papermill_json_log():
    from videotool.cloud.kernel_log import error_lines, log_text

    raw = json.dumps([
        {"stream_name": "stderr", "time": 1.0, "data": "[IPKernelApp] WARNING | TCP\n"},
        {"stream_name": "stdout", "time": 2.0, "data": "cell 1 ok\n===== scene-mux.log =====\n"},
        {"stream_name": "stdout", "time": 3.0, "data": "Conversion failed: invalid param\n"},
        {"stream_name": "stderr", "time": 4.0, "data": "RuntimeError: probe failed\nfluff\n"},
    ])
    lines = error_lines(log_text(raw))
    assert lines == ["===== scene-mux.log =====", "Conversion failed: invalid param",
                     "RuntimeError: probe failed"]
    assert error_lines(log_text("not json\nlast words")) == ["last words"]


def test_no_duplicate_notifications_after_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    run_state.transition(st, "running")
    runner = _runner(kernel=COMPLETE)
    watch_mod.step(st, runner, now=3000.0)
    hermes_calls = sum(1 for c in runner.calls if c[:2] == ["hermes", "send"])
    watch_mod.step(st, _runner(kernel=COMPLETE), now=3600.0)  # a fresh daemon pass
    assert sum(1 for c in runner.calls if c[:2] == ["hermes", "send"]) == hermes_calls


def test_repeated_network_failures_park_in_watch_error_then_recover(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)

    watch_mod.step(st, _runner(kernel=RUNNING), now=1500.0)  # healthy pass first
    assert st["status"] == "running"

    class Exploding(FakeRunner):
        def __call__(self, args, timeout=0, env=None):
            self.calls.append(list(args))
            raise watch_mod.remote.RemoteError("network down")

    boom = Exploding()
    for _ in range(3):
        watch_mod.step(st, boom, now=2000.0)
    assert st["status"] == "watch-error"
    watch_mod.step(st, _runner(kernel=COMPLETE), now=2400.0)  # network back
    assert st["status"] == "done"


def test_kernel_error_lines_find_the_tpu_kernel_log(tmp_path):
    from pathlib import Path

    from videotool.cloud.kernel_log import kernel_error_lines

    class WritesLog(FakeRunner):
        def __call__(self, args, timeout=0, env=None):
            super().__call__(args, timeout=timeout, env=env)
            if args[:3] == ["kaggle", "kernels", "output"]:
                dest = Path(args[args.index("-p") + 1])
                (dest / "videotool-render-tpu.log").write_text(json.dumps(
                    [{"stream_name": "stderr", "time": 1, "data": "RunnerError: no NVENC\n"}]),
                    encoding="utf-8")
            return 0, b""

    assert kernel_error_lines(WritesLog(), "pnd4189/videotool-render-tpu") == ["RunnerError: no NVENC"]
    assert kernel_error_lines(FakeRunner(), "k") == ["(kernel không trả log)"]


def test_a_queued_run_is_not_reported_as_started_until_it_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    watch_mod.step(st, _runner(kernel=QUEUED), now=1100.0)
    assert st["status"] == "queued"
    for now in (1300.0, 1500.0):  # still waiting in Kaggle's queue
        watch_mod.step(st, _runner(kernel=QUEUED), now=now)
        assert st["status"] == "queued"
    assert st["last_event"]["event"] == "started" and "chờ" in st["last_event"]["detail"]
    watch_mod.step(st, _runner(kernel=RUNNING), now=1700.0)
    assert st["status"] == "running"


def test_a_timeout_counts_as_a_watch_failure(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    st = _state(tmp_path)
    run_state.transition(st, "running")

    class Hangs(FakeRunner):
        def __call__(self, args, timeout=0, env=None):
            if args[:3] == ["kaggle", "kernels", "status"]:
                return 0, RUNNING.encode()
            raise subprocess.TimeoutExpired(args, timeout)

    watch_mod.step(st, Hangs(), now=2000.0)
    assert st["failures"] == 1 and "timed out" in st["error"]
