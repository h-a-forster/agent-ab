"""Deterministic sampling."""

import zlib


def every_nth(n):
    """Predicate keeping the 1st, (n+1)th, (2n+1)th ... record it sees."""
    if n < 1:
        raise ValueError("n must be at least 1")
    state = {"seen": 0}

    def keep(_record):
        state["seen"] += 1
        return (state["seen"] - 1) % n == 0

    return keep


def hash_fraction(key):
    """A stable number in [0, 1) derived from ``key`` (same key, same answer, on every run)."""
    return (zlib.crc32(str(key).encode("utf-8")) % 10000) / 10000.0


def by_key(field, fraction):
    """Predicate keeping all records of a stable subset of the values of ``field``
    (about ``fraction`` of the distinct values); records without the field are dropped."""
    if not 0 <= fraction <= 1:
        raise ValueError("fraction must be between 0 and 1")

    def keep(record):
        value = record.get(field)
        return value is not None and hash_fraction(value) < fraction

    return keep
