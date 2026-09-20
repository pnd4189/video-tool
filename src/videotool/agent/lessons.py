"""`videotool agent lesson`: a render-only agent's lesson goes to the inbox, never to a reference.

The inbox is not rules. Claude verifies each entry against code or logs and only then moves it into
the reference that owns the rule, so the agent writes here and the user gets a message.
"""

from __future__ import annotations

import time
from pathlib import Path

INBOX = Path(__file__).resolve().parents[3] / ".agents/skills/make-video/references/lessons-inbox.md"
HEADING = "## "


def entry(text: str, episode: str | None, cli: str, now: float | None = None) -> str:
    """One inbox entry in the format the file documents."""
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now if now is not None else time.time()))
    lines = [f"\n## {stamp} · {cli} · {episode or 'không rõ tập'}"]
    body = [ln.strip() for ln in str(text).strip().splitlines() if ln.strip()]
    lines += [ln if ln.startswith("-") else f"- {ln}" for ln in body]
    return "\n".join(lines) + "\n"


def append(text: str, episode: str | None, cli: str, inbox: Path = INBOX) -> str:
    """Append the entry and return it. Raises when the inbox file is missing (do not invent one)."""
    if not text or not str(text).strip():
        raise ValueError("bài học rỗng")
    if not Path(inbox).is_file():
        raise FileNotFoundError(f"không thấy hộp thư {inbox}")
    written = entry(text, episode, cli)
    with open(inbox, "a", encoding="utf-8") as fh:
        fh.write(written)
    return written


def pending(inbox: Path = INBOX) -> int:
    """How many entries wait for Claude to verify: `##` headings outside the format example fence."""
    try:
        text = Path(inbox).read_text(encoding="utf-8")
    except OSError:
        return 0
    count, fenced = 0, False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith(HEADING):
            count += 1
    return count
