"""purge_stage.py: a published episode's local stage is deleted, anything else is refused untouched.

Offline only: a temp cache root and a faked `rclone lsl`, no Drive.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/make-video/scripts/purge_stage.py"
_spec = importlib.util.spec_from_file_location("purge_stage", SCRIPT)
purge_stage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(purge_stage)

MP4 = "[Tập 73] Bình Thiên Sách - Vô Tội - Thủy Ngân Kịch Độc Bịt Lối!.mp4"
DEST = "gdrive:BẢN DỊCH/Chap 73/outputs"


def _stage(root: Path, name: str = "binh-thien-chap73") -> Path:
    stage = root / name
    (stage / "outputs").mkdir(parents=True)
    (stage / "job.yaml").write_text("project: {}\n")
    (stage / "outputs" / MP4).write_bytes(b"x" * 1000)
    (stage / "outputs/description.txt").write_text("mô tả")
    (stage / "outputs/thumbnail-candidate-1.jpg").write_bytes(b"never published")
    (stage / ".videotool/review").mkdir(parents=True)
    (stage / ".videotool/review/contact-sheet.png").write_bytes(b"png")
    (stage / ".videotool/sfx-master").mkdir()
    (stage / ".videotool/sfx-master/youtube-16x9.mp4").write_bytes(b"m" * 500)
    for suffix in ("-dl", "-kcpu"):
        (root / f"{name}{suffix}").mkdir()
        (root / f"{name}{suffix}/payload").write_bytes(b"p" * 100)
    return stage


def _published(stage: Path) -> dict[str, int]:
    return {p.name: p.stat().st_size for p in (stage / "outputs").iterdir()
            if not p.name.startswith("thumbnail-candidate-")}


def test_purge_deletes_the_stage_and_its_siblings_and_keeps_the_review(tmp_path, monkeypatch):
    stage = _stage(tmp_path)
    neighbours = [tmp_path / "binh-thien-chap7", tmp_path / "binh-thien-chap73-kcpu.log", tmp_path / "_kept"]
    neighbours[0].mkdir()
    neighbours[1].write_text("run log")
    neighbours[2].mkdir()
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: _published(stage) if dest == DEST else {})
    removed, freed, kept = purge_stage.purge(stage, DEST, cache_root=tmp_path)
    assert [p.name for p in removed] == ["binh-thien-chap73", "binh-thien-chap73-dl", "binh-thien-chap73-kcpu"]
    assert not any(p.exists() for p in removed)
    assert freed == 1000 + len("mô tả".encode()) + len(b"never published") + len("project: {}\n") + 500 + 200
    assert kept == tmp_path / "binh-thien-chap73-review"
    assert (kept / "contact-sheet.png").read_bytes() == b"png"
    assert all(p.exists() for p in neighbours)


def test_purge_also_deletes_the_colab_bundle_folder(tmp_path, monkeypatch):
    stage = _stage(tmp_path)
    colab = tmp_path / "binh-thien-chap73-colab"
    colab.mkdir()
    (colab / "bundle.vtb").write_bytes(b"b" * 10)
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: _published(stage))
    removed, _, _ = purge_stage.purge(stage, DEST, cache_root=tmp_path)
    assert colab in removed and not colab.exists()


def test_purge_also_deletes_the_vps_bundle_folder(tmp_path, monkeypatch):
    stage = _stage(tmp_path)
    vps = tmp_path / "binh-thien-chap73-vps"
    vps.mkdir()
    (vps / "bundle.vtb").write_bytes(b"b" * 10)
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: _published(stage))
    removed, _, _ = purge_stage.purge(stage, DEST, cache_root=tmp_path)
    assert vps in removed and not vps.exists()


def test_purge_replaces_the_review_of_an_earlier_render(tmp_path, monkeypatch):
    stage = _stage(tmp_path)
    (tmp_path / "binh-thien-chap73-review").mkdir()
    (tmp_path / "binh-thien-chap73-review/old.png").write_bytes(b"old")
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: _published(stage))
    _, _, kept = purge_stage.purge(stage, DEST, cache_root=tmp_path)
    assert sorted(p.name for p in kept.iterdir()) == ["contact-sheet.png"]


@pytest.mark.parametrize("remote", [
    {},                                                    # nothing on Drive
    {MP4: 1000},                                           # description.txt missing
    {MP4: 999, "description.txt": len("mô tả".encode())},  # mp4 cut short
])
def test_purge_refuses_until_every_output_is_on_drive_at_its_size(tmp_path, monkeypatch, remote):
    stage = _stage(tmp_path)
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: remote)
    with pytest.raises(purge_stage.PurgeError, match="same size"):
        purge_stage.purge(stage, DEST, cache_root=tmp_path)
    assert (stage / "outputs" / MP4).exists() and (tmp_path / "binh-thien-chap73-dl/payload").exists()


def test_purge_refuses_a_stage_that_published_no_mp4(tmp_path, monkeypatch):
    stage = _stage(tmp_path)
    (stage / "outputs" / MP4).unlink()
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: _published(stage))
    with pytest.raises(purge_stage.PurgeError, match="no mp4"):
        purge_stage.purge(stage, DEST, cache_root=tmp_path)
    assert stage.exists()


def test_purge_refuses_anything_but_a_stage_directly_under_the_cache_root(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    outside = _stage(tmp_path / "elsewhere")
    kept = _stage(root / "_kept")
    nested = _stage(root / "binh-thien-chap73", "inner")
    (root / "models").mkdir()
    link = root / "binh-thien-chap74"
    link.symlink_to(outside)
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: pytest.fail("checked a non-stage"))
    for target in (root, outside, root / "_kept", kept, nested, root / "models", link):
        with pytest.raises(purge_stage.PurgeError):
            purge_stage.purge(target, DEST, cache_root=root)
    assert all(p.exists() for p in (outside, kept, nested, root / "models", link))


def test_purge_never_follows_a_link_out_of_the_stage(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    stage = _stage(root)
    source = tmp_path / "mount/Parallax"
    source.mkdir(parents=True)
    (source / "clip-001.mp4").write_bytes(b"source material")
    (stage / "Parallax").symlink_to(source)
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: _published(stage))
    purge_stage.purge(stage, DEST, cache_root=root)
    assert not stage.exists()
    assert (source / "clip-001.mp4").read_bytes() == b"source material"


def test_purge_refuses_a_review_folder_that_is_a_link(tmp_path, monkeypatch):
    root = tmp_path / "cache"
    root.mkdir()
    stage = _stage(root)
    elsewhere = tmp_path / "mount"
    elsewhere.mkdir()
    (root / "binh-thien-chap73-review").symlink_to(elsewhere)
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: _published(stage))
    with pytest.raises(purge_stage.PurgeError, match="symlink"):
        purge_stage.purge(stage, DEST, cache_root=root)
    assert stage.exists() and list(elsewhere.iterdir()) == []


def test_lsl_listing_keeps_names_with_spaces():
    listing = (f" 3150606378 2026-10-15 02:39:58.123000000 {MP4}\n"
               "       4348 2026-10-15 02:40:01.000000000 description.txt\n"
               "2026/10/15 08:00:00 NOTICE: some rclone notice\n")
    assert purge_stage.parse_lsl(listing) == {MP4: 3150606378, "description.txt": 4348}


def test_cli_reports_a_refusal_and_deletes_nothing(tmp_path, monkeypatch, capsys):
    stage = _stage(tmp_path)
    monkeypatch.setattr(purge_stage, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(purge_stage, "remote_sizes", lambda dest: {})
    assert purge_stage.main([str(stage), "--published-to", DEST]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out and "same size" in out and stage.exists()
