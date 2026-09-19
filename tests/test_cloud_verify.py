"""Output verification: everything it must catch, and the clean pass."""

from __future__ import annotations

import json

from videotool.cloud import verify as verify_mod

from cloud_fakes import FakeRunner  # noqa: TID252

# A faststart mp4 head whose mvhd says exactly 100s (timescale 1000, duration 100000).
MP4_HEAD = (
    b"\x00\x00\x00\x20ftypisom" + b"\x00\x00\x02\x00"
    + b"\x00\x00\x01\x08moov"
    + b"\x00\x00\x00\x6Cmvhd" + b"\x00" * 12 + b"\x00\x00\x03\xe8\x00\x01\x86\xa0" + b"\x00" * 76
).decode("latin-1")
QA_OK = [{"name": "video_exists", "status": "pass", "message": "x"},
         {"name": "loudness_lufs", "status": "pass", "message": "-13.70 LUFS (target -14.0 ±1.5)"}]
FILES_OK = ["Bình Thiên Tập 1.mp4", "quality-report.json", "description.txt",
            "captions.youtube.srt", "thumbnail-1280x720.jpg"]
DESC = "Mô tả ổn.\n\n==== TAGS ====\ntruyện, audio"


class SmartRunner(FakeRunner):
    """Routes rclone cat/lsf by the remote path inside the args."""

    def __init__(self, listing=FILES_OK, qa=QA_OK, desc=DESC, head=MP4_HEAD):
        super().__init__()
        self.listing, self.qa, self.desc, self.head = listing, qa, desc, head

    def __call__(self, args, timeout=0, env=None):
        super().__call__(args, timeout=timeout, env=env)
        joined = " ".join(args)
        if "quality-report.json" in joined:
            qa = self.qa if isinstance(self.qa, str) else json.dumps(self.qa)
            return 0, qa.encode("utf-8")
        if "description.txt" in joined:
            return 0, self.desc.encode("utf-8")
        if "--head" in joined:
            return 0, self.head.encode("latin-1")
        if "lsf" in joined:
            sized = (n if "\t" in n else f"1000\t{n}" for n in self.listing)
            return 0, "\n".join(sized).encode("utf-8")
        return 0, b""


def _state(**over):
    st = {"slug": "s", "output": "gdrive:out", "expected_seconds": 100.0, "intro_cta_seconds": 8.7}
    st.update(over)
    return st


def test_clean_output_passes():
    result = verify_mod.verify_output(SmartRunner(), _state())
    assert result["ok"], result


def test_duration_mismatch_fails():
    result = verify_mod.verify_output(SmartRunner(), _state(expected_seconds=250.0))
    assert not result["ok"] and any("độ dài" in f for f in result["findings"])


def test_qa_fail_and_missing_files_fail():
    qa = QA_OK + [{"name": "resolution", "status": "fail", "message": "640x360"}]
    listing = ["Tập 1.mp4", "quality-report.json", "description.txt"]
    result = verify_mod.verify_output(SmartRunner(listing=listing, qa=qa), _state())
    assert any("resolution" in f for f in result["findings"])
    assert any("thumbnail" in f for f in result["findings"])
    assert any("captions.youtube.srt" in f for f in result["findings"])


def test_cjk_oversize_and_placeholder_description_fail():
    cjk = verify_mod.verify_output(SmartRunner(desc="Mô tả có 平天策\n==== TAGS ====\nx"), _state())
    assert any("chữ Trung" in f for f in cjk["findings"])
    long = verify_mod.verify_output(SmartRunner(desc="x" * 5000 + "\n==== TAGS ====\na"), _state())
    assert any("5000" in f for f in long["findings"])
    placeholder = verify_mod.verify_output(SmartRunner(desc="{{SUMMARY}}\n==== TAGS ===="), _state())
    assert any("placeholder" in f for f in placeholder["findings"])


def test_loudness_out_of_range_fails_but_unmeasurable_only_warns():
    loud_bad = SmartRunner(qa=[{"name": "loudness_lufs", "status": "pass", "message": "-10.00 LUFS"}])
    assert any("loudness" in f for f in verify_mod.verify_output(loud_bad, _state())["findings"])
    quiet = SmartRunner(qa=[{"name": "loudness_lufs", "status": "warn",
                             "message": "could not measure integrated LUFS"}])
    result = verify_mod.verify_output(quiet, _state())
    assert result["ok"] and any("loudness" in w for w in result["warnings"])


def test_missing_mp4_fails_immediately():
    result = verify_mod.verify_output(SmartRunner(listing=["description.txt"]), _state())
    assert not result["ok"] and result["findings"] == ["không thấy mp4 trong gdrive:out"]


def test_zero_byte_mp4_fails():
    listing = ["0\tTập 1.mp4"] + FILES_OK[1:]
    result = verify_mod.verify_output(SmartRunner(listing=listing), _state())
    assert any("0 byte" in f for f in result["findings"])


def test_malformed_quality_report_is_a_finding_not_a_crash():
    for qa in ('{"not": "a list"}', "[1, 2, 3]"):
        result = verify_mod.verify_output(SmartRunner(qa=qa), _state())
        assert isinstance(result["ok"], bool)
    assert any("quality-report" in f for f in verify_mod.verify_output(SmartRunner(qa="{}"), _state())["findings"])
