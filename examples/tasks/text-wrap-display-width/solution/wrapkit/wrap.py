"""Greedy word wrapping."""

from __future__ import annotations

from .ansi import close_styles, tokens
from .width import char_width, display_width


def _split_long(word: str, width: int) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    used = 0
    for is_ansi, piece in tokens(word):
        if is_ansi:
            cur.append(piece)
            continue
        w = char_width(piece)
        if w > 0 and used > 0 and used + w > width:
            chunks.append("".join(cur))
            cur, used = [], 0
        cur.append(piece)
        used += w
    chunks.append("".join(cur))
    return chunks


def wrap(text: str, width: int) -> list[str]:
    """Wrap ``text`` into lines of at most ``width`` columns."""
    if width < 1:
        raise ValueError("width must be at least 1")
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current: str | None = None
        for word in words:
            wwidth = display_width(word)
            if wwidth > width:
                if current is not None:
                    lines.append(current)
                chunks = _split_long(word, width)
                lines.extend(chunks[:-1])
                current = chunks[-1]
            elif current is None:
                current = word
            elif display_width(current) + 1 + wwidth <= width:
                current += " " + word
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return close_styles(lines)
