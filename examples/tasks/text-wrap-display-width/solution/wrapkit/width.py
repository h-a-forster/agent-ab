"""Measuring text."""

from __future__ import annotations

import unicodedata

from .ansi import strip_ansi


def char_width(ch: str) -> int:
    """Number of terminal columns used by a single character."""
    if unicodedata.category(ch) in ("Mn", "Me", "Cc", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def display_width(text: str) -> int:
    """Number of terminal columns used by ``text``."""
    return sum(char_width(ch) for ch in strip_ansi(text))
