"""Greedy word wrapping."""

from __future__ import annotations

from .width import display_width


def wrap(text: str, width: int) -> list[str]:
    """Wrap ``text`` into lines of at most ``width`` columns (words longer than that overflow)."""
    if width < 1:
        raise ValueError("width must be at least 1")
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            if display_width(current) + 1 + display_width(word) <= width:
                current += " " + word
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines
