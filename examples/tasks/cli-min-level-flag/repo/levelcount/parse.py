"""Parsing of log lines into severity levels."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

# Ordered from least to most severe.
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ALIASES = {"WARN": "WARNING", "FATAL": "CRITICAL", "ERR": "ERROR"}


def level_of(line: str) -> str | None:
    """Return the canonical level of a log line, or None if it has none.

    Lines look like ``2024-05-01T10:00:00 WARNING disk almost full``: the level is the second
    whitespace-separated field, optionally in brackets (``[warn]``), case-insensitive.
    """
    parts = line.split(None, 2)
    if len(parts) < 2:
        return None
    word = parts[1].strip("[]:").upper()
    word = ALIASES.get(word, word)
    return word if word in LEVELS else None


def count_levels(lines: Iterable[str]) -> Counter[str]:
    """Count lines per canonical level; lines without a recognised level are ignored."""
    counts: Counter[str] = Counter()
    for line in lines:
        level = level_of(line)
        if level is not None:
            counts[level] += 1
    return counts
