"""Parsing of a single cron field."""

from __future__ import annotations


class CronError(ValueError):
    """Invalid cron expression."""


def parse_field(text: str, lo: int, hi: int) -> frozenset[int]:
    """Expand ``text`` (``*``, ``5``, ``1-5``, ``1,3,5``) into the set of allowed values."""
    values: set[int] = set()
    for item in text.split(","):
        if item == "*":
            values.update(range(lo, hi + 1))
        elif "-" in item:
            start_s, _, end_s = item.partition("-")
            start, end = _number(start_s, lo, hi), _number(end_s, lo, hi)
            if start > end:
                raise CronError(f"reversed range: {item!r}")
            values.update(range(start, end + 1))
        else:
            values.add(_number(item, lo, hi))
    return frozenset(values)


def _number(text: str, lo: int, hi: int) -> int:
    if not text.isdigit():
        raise CronError(f"not a number: {text!r}")
    value = int(text)
    if not lo <= value <= hi:
        raise CronError(f"{value} is outside {lo}-{hi}")
    return value
