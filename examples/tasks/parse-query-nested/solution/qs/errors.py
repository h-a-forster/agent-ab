"""Error types."""

from __future__ import annotations


class ParseError(ValueError):
    """The query string cannot be represented (conflicting keys, nesting too deep, ...)."""
