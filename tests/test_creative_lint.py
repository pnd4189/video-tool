"""`creative lint` rules (unit) and `videotool prepare`'s gdrive-mount refusal."""

from __future__ import annotations

from pathlib import Path



from videotool.creative import lint_checks as lc


def _sfx(cues: list[dict], pack: str = "p") -> dict:
    return {"enhance": {"sfx": {"pack": pack, "cues": cues}}}


def test_cjk_in_description_or_project_is_an_error() -> None:
    errors, _ = lc.check_cjk({"project": {"title": "Truyện 平天策"}}, "clean")
    assert errors and set("平天策") <= set(errors[0])
    assert lc.check_cjk({"project": {"title": "Sạch"}}, "sạch")[0] == []


def test_description_over_the_limit_and_leftover_placeholders() -> None:
    long = "x" * 5000 + "\n==== TAGS ====\na, b"
    assert any("5000" in e for e in lc.check_description(long)[0])
    assert any("{{SUMMARY}}" in e for e in lc.check_description("{{SUMMARY}}\n==== TAGS ====")[0])
    assert lc.check_description("ok\n==== TAGS ====\nt")[0] == []
    assert lc.check_description(None) == ([], ["no *_DESCRIPTION_TEMPLATE.txt in the job root — "
                                                "package will not write description.txt"])


def test_sfx_unknown_file_is_an_error_when_the_pack_is_missing() -> None:
    # A pack directory that does not exist makes every cue an unknown-file error.
    errors, _, _ = lc.check_sfx(_sfx([{"time": 100.0, "file": "a.mp3"}]), Path("/nonexistent-pack"), 1000.0)
    assert errors == ["SFX a.mp3 @ 100.00s: not in pack nonexistent-pack"]


def test_sfx_drops_explained_against_a_real_pack_dir(tmp_path: Path) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "a.mp3").write_bytes(b"x")
    errors, warnings, _ = lc.check_sfx(_sfx([
        {"time": 100.0, "file": "a.mp3"},
        {"time": 115.0, "file": "a.mp3"},   # spacing
        {"time": 200.0, "file": "b.mp3"},   # unknown
        {"time": 990.0, "file": "a.mp3"},   # tail
    ]), pack, 1000.0)
    assert errors == ["SFX b.mp3 @ 200.00s: not in pack pack"]
    assert len(warnings) == 2 and "previous kept cue" in warnings[0] and "last 25s" in warnings[1]


def _music(job: Path) -> Path:
    (job / "Music").mkdir(parents=True)
    (job / "Music" / "01-a.mp3").write_bytes(b"x")
    (job / "Music" / "02-b.mp3").write_bytes(b"x")
    return job


def test_music_track_index_and_coverage_errors(tmp_path: Path) -> None:
    job = _music(tmp_path)
    good = {"audio": {"music_schedule": [
        {"track": 1, "start": 0.0, "end": 50.0}, {"track": "02-b", "start": 50.0, "end": 100.0}]}}
    assert lc.check_music(good, job, "Music", 100.0) == ([], [])
    bad = {"audio": {"music_schedule": [
        {"track": 3, "start": 0.0, "end": 40.0},        # out of range
        {"track": "khong-co", "start": 40.0, "end": 60.0},  # no match
        {"track": 1, "start": 65.0, "end": 80.0},       # gap 60 -> 65
    ]}}
    errors, _ = lc.check_music(bad, job, "Music", 100.0)
    assert len(errors) == 4  # index, name, gap, ends early


def test_title_card_warnings(tmp_path: Path) -> None:
    thumb = tmp_path / "Ảnh bìa Thumbnail-Intro"
    thumb.mkdir()
    (thumb / "37.jpg").write_bytes(b"x")
    (thumb / "38.jpg").write_bytes(b"x")
    _, warnings = lc.check_title_cards(tmp_path, {}, {})
    assert any("2 thumbnail candidates" in w for w in warnings)
    (thumb / "37.jpg").unlink()
    _, warnings = lc.check_title_cards(tmp_path, {}, {"intro_image": "Ảnh bìa Thumbnail-Intro/38.jpg"})
    assert warnings == ["no ending_image (0 candidate(s)) — the last 10s have no ending card"]


def test_parallax_missing_clips_is_an_error_unless_opted_in() -> None:
    creative = {"enhance": {"parallax": True}}
    data = {"enhance": {"parallax": True}}
    errors, _ = lc.check_parallax(creative, data, stills=12)
    assert errors and "12 story still(s)" in errors[0]
    assert lc.check_parallax({"enhance": {"parallax": True, "parallax_on_box": True}}, data, 12) == \
        ([], ["12 still(s) will get depth parallax ON THE BOX (hours) — parallax_on_box is set"])


def test_prepare_refuses_a_folder_inside_the_gdrive_mount(tmp_path: Path, monkeypatch) -> None:
    from videotool.cli import creative_commands as cc

    mount = tmp_path / "gdrive"
    folder = mount / "1. YOUTUBE AUDIO" / "Chap 55"
    monkeypatch.setenv("VIDEOTOOL_GDRIVE_MOUNT", str(mount))
    folder.mkdir(parents=True)
    assert cc.prepare(folder, "local", None) == 2
    assert not (folder / "job.yaml").exists()
    outside = tmp_path / "stage" / "Chap 55"
    outside.mkdir(parents=True)
    # No voice in the folder: prepare must fail AFTER the mount check, with a clear error.
    assert cc.prepare(outside, "local", None) == 1


def test_sfx_cue_without_a_usable_time_is_reported_not_silently_dropped() -> None:
    errors, _, explained = lc.check_sfx(_sfx([{"file": "a.mp3"}, {"time": "12:30", "file": "a.mp3"}]),
                                        Path("/nonexistent-pack"), 1000.0)
    assert len(errors) == 2 and all("usable numeric `time`" in e for e in errors)
    assert explained == []  # neither cue reaches the box's filter


def test_music_cue_with_a_non_numeric_span_is_an_error_not_a_crash(tmp_path: Path) -> None:
    creative = {"audio": {"music_schedule": [{"track": 1, "start": "0:00", "end": 100}]}}
    errors, _ = lc.check_music(creative, tmp_path, None, 100.0)
    assert any("start/end must be numbers" in e for e in errors)


def test_stand_in_failure_becomes_an_error_in_the_report(tmp_path: Path) -> None:
    from videotool.creative.lint import lint

    creative = tmp_path / "creative.yaml"
    creative.write_text("project: {title: X}\n", encoding="utf-8")
    empty = tmp_path / "episode"
    empty.mkdir()
    report = lint(str(empty), creative)   # no narration audio at the root
    assert report.errors and "could not build the stand-in" in report.errors[0]


def test_stand_in_copies_every_scene_plan_name_find_scene_plan_accepts() -> None:
    from videotool.creative.standin import is_text

    for name in ("BT55_scene_anchors.md", "BT55_scene_anchors_v2.md", "scene-anchors.md",
                 "scene_plan.md", ".work/scene-plan.md", "chap55_vi_qa.srt", "chap55_vi_qa.txt"):
        assert is_text(name), name
    for name in ("Image/01.png", "voice.wav", "notes.md", "Kịch bản/x_scene_anchors.md"):
        assert not is_text(name), name


def test_sfx_spread_reuse_and_missing_pack() -> None:
    kept = lambda t, f: ({"time": t, "file": f}, None)  # noqa: E731
    explained = [kept(100, "a.mp3"), kept(200, "a.mp3"), kept(300, "a.mp3"), kept(1300, "b.mp3")]
    chapters = [{"start": 0, "title": "Chương 1"}, {"start": 1000, "title": "Chương 2"},
                {"start": 2000, "title": "Chương 3"}]
    errors, _, counts = lc.check_sfx_spread(explained, chapters, 3000.0)
    assert counts == [3, 1, 0]
    assert any("a.mp3 is used 3 times" in e for e in errors)
    assert any("Chương 3" in e for e in errors) and not any("Chương 2" in e for e in errors)
    short = [{"start": 0, "title": "A"}, {"start": 2900, "title": "B"}]   # B is under 5 min
    assert not any("B" in e for e in lc.check_sfx_spread([kept(100, "x.mp3")], short, 3000.0)[0])


def test_sfx_without_a_pack_and_an_episode_without_sfx() -> None:
    errors, _, _ = lc.check_sfx({"enhance": {"sfx": {"cues": [{"time": 100.0, "file": "a.mp3"}]}}},
                                Path("/nonexistent/dao-si"), 1000.0)
    assert any("pack: dao-si" in e for e in errors)
    assert lc.check_sfx({}, Path("/p"), 1000.0)[1] == ["no SFX cues — audio-story episodes carry one-shot "
                                                         "SFX by default"]


def test_title_cards_ignore_a_previous_render_outputs_folder(tmp_path: Path) -> None:
    from videotool.creative.detect import detect_intro_ending_cta

    (tmp_path / "Ảnh bìa Thumbnail-Intro").mkdir()
    (tmp_path / "Ảnh bìa Thumbnail-Intro" / "22.jpg").write_bytes(b"")
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "thumbnail-1280x720.jpg").write_bytes(b"")
    data: dict = {}
    detect_intro_ending_cta(tmp_path, data)
    assert data["inputs"]["intro_image"] == "Ảnh bìa Thumbnail-Intro/22.jpg"


def test_input_overrides_must_stay_inside_the_episode(tmp_path: Path) -> None:
    import pytest

    from videotool.creative.prepare import apply_input_overrides
    from videotool.creative.rules import CreativeError

    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x", encoding="utf-8")   # exists on this machine, not on the render box
    with pytest.raises(CreativeError, match="inside the episode folder"):
        apply_input_overrides(tmp_path, {}, {"description_template": str(outside)})
