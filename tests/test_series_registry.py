"""Series registry lookups and title-list matching used by `creative lint`."""

from __future__ import annotations

from pathlib import Path

from videotool.creative import series

BT_LIST = "| **54** | `Bình Thiên Sách Tập 54: Tay Không Đấm Vỡ Thần Tượng!` | 52 | hook |\n"
DS_LIST = (
    "| 38 | `Dao_Si_Quen_0109_0113.txt` | x | Đình đám Douban (MXH sách/phim TQ): Nơi Cực Âm hé lộ "
    "chân tướng \\| Đạo sĩ sợ ma - Tập 38 |\n"
)


def _entry(tmp_path: Path, text: str, pipe: bool) -> dict:
    listing = tmp_path / "titles.md"
    listing.write_text(text, encoding="utf-8")
    return {"title_source": str(listing), "title_pipe_to_dash": pipe, "channel": "Kênh A",
            "channel_url": "https://example.test/@a", "original_author": "Tác Giả", "copyright": "C"}


def test_exact_title_from_the_list_is_ok(tmp_path: Path) -> None:
    entry = _entry(tmp_path, BT_LIST, pipe=False)
    assert series.title_status("Bình Thiên Sách Tập 54: Tay Không Đấm Vỡ Thần Tượng!", entry)[0] == "ok"


def test_escaped_pipe_in_the_list_matches_the_dash_title(tmp_path: Path) -> None:
    entry = _entry(tmp_path, DS_LIST, pipe=True)
    title = "Đình đám Douban (MXH sách/phim TQ): Nơi Cực Âm hé lộ chân tướng - Đạo sĩ sợ ma - Tập 38"
    assert series.title_status(title, entry)[0] == "ok"


def test_a_trailing_parenthetical_is_reported_as_extended(tmp_path: Path) -> None:
    entry = _entry(tmp_path, DS_LIST, pipe=True)
    title = "Đình đám Douban (MXH sách/phim TQ): Nơi Cực Âm hé lộ chân tướng - Đạo sĩ sợ ma - Tập 38 (Tập Cuối)"
    status, detail = series.title_status(title, entry)
    assert status == "extended" and "(Tập Cuối)" in detail


def test_an_invented_title_is_missing(tmp_path: Path) -> None:
    entry = _entry(tmp_path, BT_LIST, pipe=False)
    assert series.title_status("Bình Thiên Sách Tập 54: Tự Chế", entry)[0] == "missing"


def test_an_unreadable_list_is_unverified_not_an_error(tmp_path: Path) -> None:
    entry = {"title_source": str(tmp_path / "nope.md")}
    assert series.title_status("x", entry)[0] == "unverified"


def test_metadata_mismatch_names_the_field(tmp_path: Path) -> None:
    entry = _entry(tmp_path, BT_LIST, pipe=False)
    found = series.metadata_mismatches({"channel": "Kênh B", "channel_url": "https://example.test/@a",
                                        "original_author": "Tác Giả", "copyright": "C"}, entry)
    assert len(found) == 1 and "channel" in found[0]


def test_series_matched_by_file_prefix() -> None:
    entries = [{"id": "binh-thien", "stem_prefix": "Binh_Thien_Sach_"}, {"id": "dao-si", "stem_prefix": "Dao_Si_Quen_"}]
    assert series.match_series(entries, ["Image/1.jpg", "Dao_Si_Quen_0109_0113_vi_qa.srt"])["id"] == "dao-si"
    assert series.match_series(entries, ["voice.wav"]) is None


def test_repo_registry_is_found_and_loads() -> None:
    registry = series.find_registry(Path(__file__).parent)
    assert registry is not None
    ids = {e["id"] for e in series.load_series(registry)}
    assert {"binh-thien", "dao-si"} <= ids
