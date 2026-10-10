"""ANSI SGR escape handling."""

from __future__ import annotations

import re

SGR = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Remove SGR escape sequences."""
    return SGR.sub("", text)


def tokens(text: str) -> list[tuple[bool, str]]:
    """Split ``text`` into ``(is_ansi, piece)`` tokens: one per SGR sequence or character."""
    out: list[tuple[bool, str]] = []
    pos = 0
    for match in SGR.finditer(text):
        out.extend((False, ch) for ch in text[pos : match.start()])
        out.append((True, match.group()))
        pos = match.end()
    out.extend((False, ch) for ch in text[pos:])
    return out
