from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.core.chapter_timing import derive_chapters


def _seg(start: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(start=start, end=start + 5.0, text=text)


def _aligned(*texts_at: tuple[float, str]) -> TranscriptResult:
    return TranscriptResult(language="vi", segments=[_seg(s, t) for s, t in texts_at])


def test_derive_chapters_extracts_headings_in_order() -> None:
    aligned = _aligned(
        (0.0, "Chương 11: Tri kiến chướng"),
        (12.0, "Mở đầu một ngày mới ở học viện."),
        (600.0, "Chương 12: Thần hoặc chi thượng"),
        (1200.0, "Chương 13: Thánh giả thuyết"),
    )
    chapters = derive_chapters(aligned)
    assert chapters == [
        (0.0, "Chương 11: Tri kiến chướng"),
        (600.0, "Chương 12: Thần hoặc chi thượng"),
        (1200.0, "Chương 13: Thánh giả thuyết"),
    ]


def test_first_chapter_forced_to_zero() -> None:
    aligned = _aligned(
        (3.4, "Chương 1: A"),
        (300.0, "Chương 2: B"),
        (600.0, "Chương 3: C"),
    )
    chapters = derive_chapters(aligned)
    assert chapters[0][0] == 0.0


def test_fewer_than_three_headings_returns_empty() -> None:
    aligned = _aligned((0.0, "Chương 1: A"), (300.0, "Chương 2: B"))
    assert derive_chapters(aligned) == []


def test_too_close_headings_are_dropped() -> None:
    # Second heading is <10s after the first -> dropped; result then has <3 -> empty.
    aligned = _aligned(
        (0.0, "Chương 1: A"),
        (5.0, "Chương 2: B"),
        (600.0, "Chương 3: C"),
        (1200.0, "Chương 4: D"),
    )
    chapters = derive_chapters(aligned)
    starts = [start for start, _ in chapters]
    assert 5.0 not in starts
    assert starts == [0.0, 600.0, 1200.0]
