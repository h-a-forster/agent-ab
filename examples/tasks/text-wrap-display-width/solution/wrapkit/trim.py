"""Shortening text."""

from __future__ import annotations

from .ansi import tokens, update_open
from .width import char_width, display_width


def truncate(text: str, width: int, placeholder: str = "...") -> str:
    """Shorten ``text`` to at most ``width`` columns, ending with ``placeholder``."""
    if display_width(placeholder) > width:
        raise ValueError("placeholder is wider than width")
    if display_width(text) <= width:
        return text
    budget = width - display_width(placeholder)
    out: list[str] = []
    open_seqs: list[str] = []
    used = 0
    done = False
    for is_ansi, piece in tokens(text):
        if is_ansi:
            if not done:
                out.append(piece)
                update_open(open_seqs, piece)
            continue
        w = char_width(piece)
        if done:
            continue
        if w > 0 and used + w > budget:
            done = True
            continue
        out.append(piece)
        used += w
    return "".join(out) + ("\x1b[0m" if open_seqs else "") + placeholder
