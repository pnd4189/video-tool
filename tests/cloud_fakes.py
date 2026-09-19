"""Shared fake runner for the cloud tests: scripted responses, every call recorded."""

from __future__ import annotations

from pathlib import Path


class FakeRunner:
    def __init__(self, responses: dict[tuple, tuple[int, str]] | None = None):
        self.responses = responses or {}
        self.calls: list[list[str]] = []
        self.uploads: dict[str, str] = {}  # copyto destination -> file content at call time

    def __call__(self, args: list[str], timeout: float = 0, env: dict | None = None) -> tuple[int, str]:
        self.calls.append(list(args))
        self._capture_uploads(args)
        key = tuple(args[:3])
        for prefix in sorted(self.responses, key=len, reverse=True):  # longest match wins
            if tuple(args[: len(prefix)]) == prefix:
                code, out = self.responses[prefix]
                return code, self._bytes(out)
        return 0, b""

    @staticmethod
    def _bytes(value):
        return value.encode("utf-8") if isinstance(value, str) else value

    def _capture_uploads(self, args):
        if args[:2] == ["rclone", "copyto"]:
            try:
                self.uploads[args[-1]] = Path(args[2]).read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

    def seen(self, *prefix: str) -> bool:
        return any(call[: len(prefix)] == list(prefix) for call in self.calls)
