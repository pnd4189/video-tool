"""The lessons inbox: format, append-only, and the pending count the hooks show."""

from __future__ import annotations

from pathlib import Path

import pytest

from videotool.agent import lessons

INTRO = """# Lessons inbox — NOT rules; waiting for Claude to verify

Entry format:

```
## YYYY-MM-DD <agent> <episode slug>
- What happened:
```
"""


def _inbox(tmp_path: Path) -> Path:
    path = tmp_path / "lessons-inbox.md"
    path.write_text(INTRO, encoding="utf-8")
    return path


def test_entry_carries_time_cli_and_episode() -> None:
    written = lessons.entry("cue bị bỏ vì sát CTA", "binh-thien-chap55", "agy", now=0.0)
    assert written.startswith("\n## 1970-01-01 00:00 UTC · agy · binh-thien-chap55\n")
    assert "- cue bị bỏ vì sát CTA" in written


def test_multiline_text_becomes_bullets_and_keeps_existing_ones() -> None:
    written = lessons.entry("What happened: x\n- Evidence: y\n\nSuggested rule: z", None, "agy", now=0.0)
    assert written.splitlines()[2:] == ["- What happened: x", "- Evidence: y", "- Suggested rule: z"]
    assert "không rõ tập" in written


def test_append_adds_to_the_end_and_never_rewrites(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)
    lessons.append("first", "ep1", "agy", inbox)
    lessons.append("second", "ep2", "agy", inbox)
    text = inbox.read_text(encoding="utf-8")
    assert text.startswith(INTRO)
    assert text.index("first") < text.index("second")


def test_the_pending_count_ignores_the_format_example(tmp_path: Path) -> None:
    inbox = _inbox(tmp_path)
    assert lessons.pending(inbox) == 0        # only the fenced example is there
    lessons.append("first", "ep1", "agy", inbox)
    assert lessons.pending(inbox) == 1
    assert lessons.pending(tmp_path / "missing.md") == 0


def test_an_empty_lesson_or_a_missing_inbox_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        lessons.append("   ", "ep", "agy", _inbox(tmp_path))
    with pytest.raises(FileNotFoundError):
        lessons.append("real lesson", "ep", "agy", tmp_path / "nope.md")


def test_the_real_inbox_ships_with_nothing_pending() -> None:
    assert lessons.INBOX.is_file()
    assert lessons.pending() >= 0
