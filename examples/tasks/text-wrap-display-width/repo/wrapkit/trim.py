"""Shortening text."""

from __future__ import annotations

from .width import display_width


def truncate(text: str, width: int, placeholder: str = "...") -> str:
    """Shorten ``text`` to at most ``width`` columns, ending with ``placeholder``."""
    if display_width(placeholder) > width:
        raise ValueError("placeholder is wider than width")
    if display_width(text) <= width:
        return text
    return text[: width - len(placeholder)] + placeholder
