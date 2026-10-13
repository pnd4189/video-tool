"""The Kaggle CPU lane scripts: ids, safety refusals, metadata, bundle, preflight, CLI parsing, verify.

Offline only: temp git repos and tiny ffmpeg-made media, no Kaggle, no Drive.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/make-video/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


kcpu = _load("kaggle_cpu_render")
box = _load("kaggle_cpu_box")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=repo,
                          check=True, capture_output=True, text=True).stdout


def _code_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src/videotool").mkdir(parents=True)
    (repo / "Colab").mkdir()
    (repo / "src/videotool/__init__.py").write_text("")
    (repo / "Colab/cloud_render_runner.py").write_text("x = 1\n")
    (repo / "pyproject.toml").write_text("[project]\nname = 'videotool'\n")
    (repo / "README.md").write_text("readme\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


# --- ids and safety --------------------------------------------------------------------------------

def test_ids_are_deterministic_prefixed_and_within_kaggle_limits():
    kernel, dataset = kcpu.ids_for("pnd4189", "binh-thien-chap71", "abcdef123456")
    assert kernel == "pnd4189/videotool-cpu-binh-thien-chap71-abcdef"
    assert dataset == "pnd4189/videotool-cpu-job-binh-thien-chap71-abcdef"
    assert kcpu.ids_for("pnd4189", "binh-thien-chap71", "abcdef123456") == (kernel, dataset)


def test_long_vietnamese_slug_is_folded_and_truncated():
    kernel, dataset = kcpu.ids_for("o", "Bình Thiên Sách – Chương Đặc Biệt Rất Rất Rất Dài Thật Dài", "123456")
    for ref in (kernel, dataset):
        name = ref.split("/", 1)[1]
        assert len(name) <= kcpu.MAX_SLUG_LEN
        assert name.isascii() and "--" not in name and name.endswith("-123456")


@pytest.mark.parametrize("ref", [
    "pnd4189/videotool-render",            # the frozen GPU kernel
    "pnd4189/videotool-render-tpu",        # the frozen TPU kernel
    "pnd4189/vieneu-tts-binh-thien-sach",  # someone else's kernel
    "other/videotool-cpu-x-123456",        # another owner
])
def test_refuses_any_kernel_this_lane_does_not_own(ref):
    with pytest.raises(kcpu.LaneError):
        kcpu.assert_safe_kernel_ref(ref, "pnd4189")


def test_accepts_its_own_kernel_ids():
    kernel, _ = kcpu.ids_for("pnd4189", "binh-thien-chap71", "abcdef")
    assert kcpu.assert_safe_kernel_ref(kernel, "pnd4189") == kernel


def test_kernel_metadata_is_private_cpu_only_with_one_dataset():
    meta = kcpu.kernel_metadata("pnd4189/videotool-cpu-x-123456", "pnd4189/videotool-cpu-job-x-123456")
    assert meta["is_private"] == "true"
    assert meta["enable_gpu"] == "false" and meta["enable_tpu"] == "false"
    assert meta["enable_internet"] == "true"
    assert meta["dataset_sources"] == ["pnd4189/videotool-cpu-job-x-123456"]
    assert meta["kernel_type"] == "script" and meta["code_file"] == "kaggle_cpu_box.py"
    assert meta["title"] == "videotool-cpu-x-123456"


def test_dataset_metadata_names_the_dataset():
    meta = kcpu.dataset_metadata("pnd4189/videotool-cpu-job-x-123456")
    assert meta["id"] == "pnd4189/videotool-cpu-job-x-123456"
    assert meta["title"] == "videotool-cpu-job-x-123456"


# --- credential scan -----------------------------------------------------------------------------

def test_credential_scan_passes_a_clean_stage(tmp_path):
    (tmp_path / "Image").mkdir()
    (tmp_path / "Image/1.jpg").write_bytes(b"\xff\xd8 not a key")
    (tmp_path / "job.yaml").write_text("inputs:\n  voice: v.wav\n")
    (tmp_path / "v.wav").write_bytes(b"RIFF" + b"\0" * 64)
    assert kcpu.scan_credentials(tmp_path) == []


def test_credential_scan_flags_names_and_contents(tmp_path):
    for name in ("rclone.conf", "kaggle.json", "access_token", ".env", "client_secret_123.json",
                 "deep/sub/id_rsa"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    (tmp_path / "notes.txt").write_text('token = {"refresh_token": "1//abc"}')
    hits = kcpu.scan_credentials(tmp_path)
    assert set(hits) == {"rclone.conf", "kaggle.json", "access_token", ".env", "client_secret_123.json",
                         "deep/sub/id_rsa", "notes.txt"}


# --- bundle --------------------------------------------------------------------------------------

@pytest.mark.parametrize("rel,excluded", [
    (".kaggle-cpu.json", True),
    (".videotool/tmp/clips/youtube-16x9/scene-0001.mp4", True),
    ("outputs/youtube-16x9.mp4", True),
    ("outputs/captions.srt", False),
    ("Image/---_SCENE_001_---_1.jpg", False),
    ("CTA voice/Intro CTA - with voice.mp4", False),
])
def test_bundle_excludes_only_state_temp_and_rendered_mp4(rel, excluded):
    assert kcpu.bundle_excluded(rel) is excluded


def test_bundle_holds_committed_code_and_the_stage(tmp_path):
    repo = _code_repo(tmp_path)
    (repo / "src/videotool/uncommitted.py").write_text("not shipped\n")
    stage = tmp_path / "stage"
    for rel, data in {"job.yaml": "storyboard: []\n", "outputs/captions.srt": "1\n",
                      "outputs/youtube-16x9.mp4": "old", ".kaggle-cpu.json": "{}",
                      ".videotool/tmp/x.log": "x", "CTA voice/Intro CTA - with voice.mp4": "cta"}.items():
        (stage / rel).parent.mkdir(parents=True, exist_ok=True)
        (stage / rel).write_text(data)

    bundle, digest = kcpu.build_bundle(stage, tmp_path / "out", repo=repo)

    with tarfile.open(bundle) as tar:
        names = {m.name for m in tar.getmembers() if m.isfile()}
    assert {"repo/src/videotool/__init__.py", "repo/Colab/cloud_render_runner.py", "repo/pyproject.toml",
            "repo/README.md", "job/job.yaml", "job/outputs/captions.srt",
            "job/CTA voice/Intro CTA - with voice.mp4"} <= names
    assert "repo/src/videotool/uncommitted.py" not in names
    assert not {"job/outputs/youtube-16x9.mp4", "job/.kaggle-cpu.json", "job/.videotool/tmp/x.log"} & names
    assert digest == hashlib.sha256(bundle.read_bytes()).hexdigest()
    box.verify_bundle({"bundle_bytes": bundle.stat().st_size, "bundle_sha256": digest}, bundle)


def test_box_rejects_a_bundle_that_does_not_match_its_manifest(tmp_path):
    bundle = tmp_path / box.BUNDLE_NAME
    bundle.write_bytes(b"x" * 10)
    with pytest.raises(box.BoxError, match="bytes"):
        box.verify_bundle({"bundle_bytes": 11, "bundle_sha256": "0"}, bundle)
    with pytest.raises(box.BoxError, match="sha256"):
        box.verify_bundle({"bundle_bytes": 10, "bundle_sha256": "0"}, bundle)


# --- preflight -----------------------------------------------------------------------------------

def test_narration_cap():
    kcpu.check_narration(3.5 * 3600, 3.5)
    with pytest.raises(kcpu.LaneError, match="GPU/TPU or Modal"):
        kcpu.check_narration(3.5 * 3600 + 1, 3.5)


def test_code_parity_clean_and_equal_to_origin_main(tmp_path):
    assert kcpu.code_parity_problems(_code_repo(tmp_path), committed=kcpu.CODE_PATHS) == []


def test_code_parity_refuses_uncommitted_shipped_code(tmp_path):
    repo = _code_repo(tmp_path)
    (repo / "Colab/cloud_render_runner.py").write_text("x = 2\n")
    problems = kcpu.code_parity_problems(repo, committed=kcpu.CODE_PATHS)
    assert len(problems) == 1 and "uncommitted" in problems[0]


def test_code_parity_refuses_code_not_on_origin_main(tmp_path):
    repo = _code_repo(tmp_path)
    (repo / "src/videotool/__init__.py").write_text("changed = True\n")
    _git(repo, "commit", "-q", "-am", "local only")
    problems = kcpu.code_parity_problems(repo, committed=kcpu.CODE_PATHS)
    assert len(problems) == 1 and "origin/main" in problems[0]


def test_code_parity_refuses_a_missing_origin_main(tmp_path):
    repo = _code_repo(tmp_path)
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    assert any("origin/main" in p for p in kcpu.code_parity_problems(repo, committed=kcpu.CODE_PATHS))


def test_srt_cue_bounds():
    text = "1\n00:00:08,760 --> 00:00:16,120\nChương 886\n\n2\n02:18:30,000 --> 02:18:34,420\ncuối\n"
    assert kcpu.srt_cue_bounds(text) == (8.76, 8314.42)
    with pytest.raises(kcpu.LaneError):
        kcpu.srt_cue_bounds("no cues here")


# --- kaggle CLI output parsing --------------------------------------------------------------------

@pytest.mark.parametrize("out,status,terminal", [
    ('pnd4189/x has status "KernelWorkerStatus.COMPLETE"', "complete", True),
    ('pnd4189/x has status "KernelWorkerStatus.RUNNING"', "running", False),
    ('pnd4189/x has status "KernelWorkerStatus.QUEUED"', "queued", False),
    ('pnd4189/x has status "KernelWorkerStatus.ERROR"', "error", True),
    ('pnd4189/x has status "KernelWorkerStatus.CANCEL_ACKNOWLEDGED"', "cancel_acknowledged", True),
    ("404 - Not Found", "unknown", False),
])
def test_parse_status_and_terminal(out, status, terminal):
    assert kcpu.parse_status(out) == status
    assert kcpu.is_terminal(status) is terminal


def test_dataset_errors_are_detected_even_with_exit_zero():
    assert kcpu.cli_error("Dataset creation error: Invalid license")
    assert not kcpu.cli_error("Your private Dataset is being created. Please check progress at https://x")


LISTING = """name                size  creationDate
-------------  ---------  --------------------------
bundle.vtb     930478080  2026-10-12 07:12:05.006000
manifest.json        459  2026-10-12 07:11:41.586000
"""


def test_dataset_listing_is_parsed_from_the_real_table():
    assert kcpu.parse_dataset_files(LISTING) == {"bundle.vtb": 930478080, "manifest.json": 459}
    assert kcpu.parse_dataset_files(
        "403 Client Error: Forbidden for url: https://api.kaggle.com/v1/datasets.DatasetApiService/x") == {}


def test_dataset_is_ready_only_with_the_bundle_at_its_exact_size():
    assert kcpu.dataset_has_files(LISTING, {"bundle.vtb": 930478080, "manifest.json": None})
    assert not kcpu.dataset_has_files(LISTING, {"bundle.vtb": 930478081, "manifest.json": None})
    assert not kcpu.dataset_has_files("404 - Not Found", {"bundle.vtb": None})


def test_latest_box_line_prefers_heartbeats():
    log = ("[   1.0s] box: python 3.12\n[ 300.0s] heartbeat: 10/244 clips, 5 min\n"
           "pip noise\n[ 600.0s] heartbeat: 30/244 clips, 10 min\n[ 601.0s] other\n")
    assert kcpu.latest_box_line(log) == "[ 600.0s] heartbeat: 30/244 clips, 10 min"
    assert kcpu.latest_box_line("[  12.3s] encoder pinned: libx264\n") == "[  12.3s] encoder pinned: libx264"
    assert kcpu.latest_box_line("") == ""


# --- box helpers ---------------------------------------------------------------------------------

@pytest.mark.parametrize("parts", [("binh-thien",), ("datasets", "pnd4189", "videotool-cpu-job-x")])
def test_box_finds_the_manifest_in_either_kaggle_input_layout(tmp_path, parts):
    folder = tmp_path.joinpath(*parts)
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{}")
    (folder / box.BUNDLE_NAME).write_bytes(b"")
    assert box.find_manifest(tmp_path) == folder / "manifest.json"


def test_box_refuses_a_missing_or_ambiguous_manifest(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a/manifest.json").write_text("{}")  # no bundle beside it
    with pytest.raises(box.BoxError):
        box.find_manifest(tmp_path)
    for name in ("b", "c"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "manifest.json").write_text("{}")
        (tmp_path / name / box.BUNDLE_NAME).write_bytes(b"")
    with pytest.raises(box.BoxError):
        box.find_manifest(tmp_path)


def test_driver_and_box_agree_on_the_bundle_name():
    assert kcpu.BUNDLE_NAME == box.BUNDLE_NAME and not box.BUNDLE_NAME.endswith((".tar", ".zip", ".gz"))


def test_box_scratch_is_the_roomiest_existing_dir_or_a_refusal(tmp_path):
    assert box.pick_scratch((tmp_path / "missing", tmp_path), min_free=0) == tmp_path
    with pytest.raises(box.BoxError, match="scratch space"):
        box.pick_scratch((tmp_path,), min_free=10**9)
    with pytest.raises(box.BoxError):
        box.pick_scratch((tmp_path / "missing",), min_free=0)


def test_box_only_accepts_x264():
    assert box.require_cpu_encoder("libx264-balanced-capped-2500k") == "libx264-balanced-capped-2500k"
    with pytest.raises(box.BoxError):
        box.require_cpu_encoder("h264_nvenc-capped-2500k")


# --- local verify on real (tiny) media ------------------------------------------------------------

def _media(path: Path, seconds: float, video: bool, video_seconds: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if video:
        cmd += ["-f", "lavfi", "-t", str(video_seconds or seconds), "-i", "color=c=black:s=1920x1080:r=30"]
    cmd += ["-f", "lavfi", "-t", str(seconds), "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += (["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac"] if video else [])
    subprocess.run([*cmd, str(path)], check=True)


def _stage_for_verify(tmp_path: Path, final_seconds: float, srt_start: str,
                      final_video_seconds: float | None = None) -> Path:
    stage = tmp_path / "stage"
    _media(stage / "CTA voice/intro.mp4", 0.5, video=True)
    _media(stage / "voice.wav", 1.0, video=False)
    _media(stage / "CTA voice/outro.mp4", 0.5, video=True)
    _media(stage / "outputs/[Tập 71] Bình Thiên Sách.mp4", final_seconds, video=True,
           video_seconds=final_video_seconds)
    (stage / "job.yaml").write_text(json.dumps({"inputs": {
        "voice": "voice.wav", "intro_cta": "CTA voice/intro.mp4", "outro_cta": "CTA voice/outro.mp4"}}))
    (stage / "outputs/captions.youtube.srt").write_text(f"1\n{srt_start} --> 00:00:01,000\nChương 901\n")
    return stage


@needs_ffmpeg
def test_verify_accepts_a_correct_final_video(tmp_path):
    kcpu.verify(_stage_for_verify(tmp_path, 2.0, "00:00:00,500"))


@needs_ffmpeg
def test_verify_refuses_a_cut_video(tmp_path):
    with pytest.raises(kcpu.LaneError, match="duration"):
        kcpu.verify(_stage_for_verify(tmp_path, 3.0, "00:00:00,500"))


@needs_ffmpeg
def test_verify_tolerates_video_slightly_longer_than_audio(tmp_path):
    kcpu.verify(_stage_for_verify(tmp_path, 2.0, "00:00:00,500", final_video_seconds=2.4))


@needs_ffmpeg
def test_verify_refuses_video_far_from_audio(tmp_path):
    with pytest.raises(kcpu.LaneError, match="video stream"):
        kcpu.verify(_stage_for_verify(tmp_path, 2.0, "00:00:00,500", final_video_seconds=3.5))


@needs_ffmpeg
def test_verify_refuses_youtube_captions_not_shifted_by_the_intro(tmp_path):
    with pytest.raises(kcpu.LaneError, match="captions.youtube.srt"):
        kcpu.verify(_stage_for_verify(tmp_path, 2.0, "00:00:00,000"))


# --- step refusals that must happen before any Kaggle call ----------------------------------------

def test_submit_refuses_an_open_run(tmp_path, capsys):
    stage = tmp_path / "binh-thien-chap71"
    stage.mkdir()
    (stage / kcpu.STATE_NAME).write_text(json.dumps({"kernel_id": "pnd4189/videotool-cpu-x-1", "status": "started"}))
    assert kcpu.main(["submit", str(stage)]) == 1
    assert "already has a run" in capsys.readouterr().out


def test_cleanup_refuses_before_publish(tmp_path, capsys):
    stage = tmp_path / "binh-thien-chap71"
    stage.mkdir()
    (stage / kcpu.STATE_NAME).write_text(json.dumps({
        "kernel_id": "pnd4189/videotool-cpu-x-1", "dataset_id": "pnd4189/videotool-cpu-job-x-1",
        "owner": "pnd4189", "status": "complete"}))
    assert kcpu.main(["cleanup", str(stage)]) == 1
    assert "not published yet" in capsys.readouterr().out


def test_finish_refuses_to_mix_sfx_twice(tmp_path, capsys):
    stage = tmp_path / "binh-thien-chap71"
    (stage / "outputs").mkdir(parents=True)
    (stage / "outputs/[Tập 71] Bình Thiên Sách.mp4").write_bytes(b"already mixed")
    (stage / kcpu.STATE_NAME).write_text(json.dumps({
        "fetched": True, "dl_dir": str(tmp_path / "dl"), "result": {"mp4": "youtube-16x9.mp4"}}))
    assert kcpu.main(["finish", str(stage)]) == 1
    assert "earlier finish attempt" in capsys.readouterr().out


def test_run_and_publish_need_a_remote(tmp_path, capsys):
    assert kcpu.main(["publish", str(tmp_path)]) == 1
    assert "--remote is required" in capsys.readouterr().out


def test_publish_refuses_the_shared_render_folder(tmp_path, capsys):
    stage = tmp_path / "s"
    stage.mkdir()
    (stage / kcpu.STATE_NAME).write_text(json.dumps({"finished": True}))
    assert kcpu.main(["publish", str(stage), "--remote", "gdrive:_VIDEOTOOL_SHARED/x"]) == 1
    assert "--remote must be the episode folder" in capsys.readouterr().out
