"""Remote helpers: a slow Drive is 'unknown', never a traceback and never 'absent'."""

from __future__ import annotations

import pytest

from videotool.cloud import remote

from cloud_fakes import FakeRunner, TimeoutRunner  # noqa: TID252

SHARED = "gdrive:_VIDEOTOOL_SHARED"


def test_a_timed_out_call_is_a_remote_timeout_not_a_traceback():
    runner = TimeoutRunner(("rclone", "cat"))
    with pytest.raises(remote.RemoteTimeout):
        remote.remote_text(runner, f"{SHARED}/x.json", 120)


def test_a_remote_timeout_is_still_a_remote_error():
    assert issubclass(remote.RemoteTimeout, remote.RemoteError)


def test_a_nonzero_exit_stays_a_plain_remote_error():
    with pytest.raises(remote.RemoteError) as caught:
        remote.remote_text(FakeRunner({("rclone", "cat"): (3, "")}), f"{SHARED}/x.json", 120)
    assert not isinstance(caught.value, remote.RemoteTimeout)


def test_md5_on_a_slow_drive_is_none_so_the_guard_blocks_instead_of_crashing():
    assert remote.md5_on_remote(TimeoutRunner(("rclone", "md5sum")), f"{SHARED}/m.py") is None


def test_kernel_status_on_a_slow_cli_is_none():
    assert remote.kernel_status(TimeoutRunner(("kaggle", "kernels", "status")), "k/1") is None


def test_kernel_status_reads_the_cancel_acknowledged_state():
    runner = FakeRunner({("kaggle", "kernels", "status"):
                         (0, 'k/1 has status "KernelWorkerStatus.CANCEL_ACKNOWLEDGED"')})
    assert remote.kernel_status(runner, "k/1") == "cancelled"


def test_kernel_status_reads_the_cancel_requested_state():
    runner = FakeRunner({("kaggle", "kernels", "status"):
                         (0, 'k/1 has status "KernelWorkerStatus.CANCEL_REQUESTED"')})
    assert remote.kernel_status(runner, "k/1") == "cancelled"


def test_kernel_status_of_a_state_it_does_not_know_is_none_not_a_guess():
    runner = FakeRunner({("kaggle", "kernels", "status"):
                         (0, 'k/1 has status "KernelWorkerStatus.NEW_SCRIPT"')})
    assert remote.kernel_status(runner, "k/1") is None
