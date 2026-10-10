"""JSON value equality."""

from __future__ import annotations


def json_equal(a, b) -> bool:
    """True if ``a`` and ``b`` are equal JSON values."""
    return a == b
