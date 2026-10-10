"""Measuring text."""

from __future__ import annotations


def char_width(ch: str) -> int:
    """Number of terminal columns used by a single character."""
    return 1


def display_width(text: str) -> int:
    """Number of terminal columns used by ``text``."""
    return len(text)
