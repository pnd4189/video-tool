from pathlib import Path

from videotool.ai.align_script import align_script_to_transcript, parse_script
from videotool.ai.subtitles import validate_srt, write_srt
from videotool.ai.transcribe import TranscriptResult, TranscriptSegment


def test_parse_script_splits_paragraphs_and_sentences(tmp_path: Path) -> None:
    script = tmp_path / "script.txt"
    script.write_text(
        "Chương 1: Khởi đầu\n"
        "\n"
        "Trời mưa rất to. Anh ấy bước đi chậm rãi!\n"
        "\n"
        "Cô ấy hỏi: tại sao? Không ai trả lời…\n",
        encoding="utf-8",
    )
    cues = parse_script(script)
    assert cues[0] == "Chương 1: Khởi đầu"
    assert "Trời mưa rất to." in cues
    assert "Anh ấy bước đi chậm rãi!" in cues
    assert all(cue.strip() for cue in cues)
    assert len(cues) == 5


def test_align_distributes_sentences_across_segment_span() -> None:
    transcript = TranscriptResult(
        language="vi",
        segments=[
            TranscriptSegment(0.0, 10.0, "asr one"),
            TranscriptSegment(10.0, 20.0, "asr two"),
            TranscriptSegment(20.0, 30.0, "asr three"),
        ],
    )
    sentences = [f"Câu số {n}." for n in range(1, 7)]
    aligned = align_script_to_transcript(sentences, transcript)

    assert [segment.text for segment in aligned.segments] == sentences
    assert aligned.language == "vi"
    previous_end = 0.0
    for segment in aligned.segments:
        assert segment.start <= segment.end
        assert segment.start >= previous_end - 1e-6  # monotonic, non-overlapping
        previous_end = segment.end
    assert aligned.segments[0].start >= 0.0
    assert aligned.segments[-1].end <= 30.0 + 1e-6


def test_aligned_result_writes_valid_srt(tmp_path: Path) -> None:
    transcript = TranscriptResult(
        language="vi",
        segments=[TranscriptSegment(0.0, 12.0, "x"), TranscriptSegment(12.0, 24.0, "y")],
    )
    sentences = ["Câu một dài hơn một chút.", "Câu hai.", "Câu ba kết thúc."]
    aligned = align_script_to_transcript(sentences, transcript)
    srt_path = tmp_path / "captions.srt"
    write_srt(aligned, srt_path)
    assert validate_srt(srt_path) == []


def test_empty_script_returns_original_transcript() -> None:
    transcript = TranscriptResult(language="vi", segments=[TranscriptSegment(0.0, 5.0, "asr")])
    assert align_script_to_transcript([], transcript) is transcript
