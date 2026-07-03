from videotool.ai.transcribe import TranscriptResult, TranscriptSegment
from videotool.core.chapter_timing import chapters_from_srt, derive_chapters


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


# --- chapters_from_srt (provided-SRT path, no whisper) ---

def test_chapters_from_srt_parses_markers_and_timing() -> None:
    # Cue 2 has a leading quote (some exporters add it) + a title split across two lines;
    # cue 3 is a plain body line and must be ignored.
    srt = (
        "1\n00:00:00,000 --> 00:00:03,160\n"
        "Chương 141: Người Bắc Ngụy cũng giống\nnhau.\n\n"
        "2\n00:08:27,800 --> 00:08:31,000\n"
        "\" Chương 142: Phái Tam Thanh.\n\n"
        "3\n00:09:00,000 --> 00:09:05,000\n"
        "Một dòng nội dung bình thường.\n\n"
        "4\n00:16:56,880 --> 00:17:02,000\nChương 143: Trong cõi u minh.\n"
    )
    chapters = chapters_from_srt(srt)
    assert chapters == [
        (0.0, "Chương 141: Người Bắc Ngụy cũng giống nhau."),
        (507.8, "Chương 142: Phái Tam Thanh."),
        (1016.88, "Chương 143: Trong cõi u minh."),
    ]


def test_chapters_from_srt_tolerates_stray_blank_lines() -> None:
    # Triple newlines between cues leave a leading blank line on the next block; the parser
    # must still find each timestamp line and not silently drop chapters.
    srt = (
        "1\n00:00:00,000 --> 00:00:03,000\nChương 1: A\n\n\n"
        "2\n00:05:00,000 --> 00:05:03,000\nChương 2: B\n\n\n"
        "3\n00:10:00,000 --> 00:10:03,000\nChương 3: C\n"
    )
    chapters = chapters_from_srt(srt)
    assert [round(s, 2) for s, _ in chapters] == [0.0, 300.0, 600.0]


def test_chapters_from_srt_fewer_than_three_returns_empty() -> None:
    srt = (
        "1\n00:00:00,000 --> 00:00:03,000\nChương 1: A\n\n"
        "2\n00:05:00,000 --> 00:05:03,000\nChương 2: B\n"
    )
    assert chapters_from_srt(srt) == []
