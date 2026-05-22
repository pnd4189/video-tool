from pathlib import Path

from videotool.ai.silence import SilenceRange, write_cut_suggestions


def test_write_cut_suggestions(tmp_path: Path) -> None:
    output = tmp_path / "cuts.md"
    write_cut_suggestions([SilenceRange(1.0, 2.0)], output)
    assert "1.000s to 2.000s" in output.read_text(encoding="utf-8")
