"""Parsing of a single cron field."""

from __future__ import annotations


class CronError(ValueError):
    """Invalid cron expression."""


MONTH_NAMES = {n: i for i, n in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
DOW_NAMES = {n: i for i, n in enumerate("SUN MON TUE WED THU FRI SAT".split())}


def is_star(text: str) -> bool:
    """True for fields that start with ``*`` or are ``?``."""
    return text.startswith("*") or text == "?"


def parse_field(
    text: str, lo: int, hi: int, names: dict[str, int] | None = None, allow_question: bool = False
) -> frozenset[int]:
    """Expand ``text`` into the set of allowed values in ``lo..hi``."""
    if not text:
        raise CronError("empty field")
    values: set[int] = set()
    for item in text.split(","):
        if not item:
            raise CronError(f"empty list element in {text!r}")
        if item == "?":
            if not allow_question:
                raise CronError("'?' is not allowed in this field")
            values.update(range(lo, hi + 1))
            continue
        range_part, slash, step_s = item.partition("/")
        step = 1
        if slash:
            if not step_s.isascii() or not step_s.isdigit() or int(step_s) < 1:
                raise CronError(f"bad step in {item!r}")
            step = int(step_s)
        if range_part == "*":
            start, end = lo, hi
        elif "-" in range_part:
            a, _, b = range_part.partition("-")
            start, end = _value(a, lo, hi, names), _value(b, lo, hi, names)
            if start > end:
                raise CronError(f"reversed range: {item!r}")
        else:
            start = _value(range_part, lo, hi, names)
            end = hi if slash else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


def _value(text: str, lo: int, hi: int, names: dict[str, int] | None) -> int:
    if names and text.upper() in names:
        return names[text.upper()]
    if not text.isascii() or not text.isdigit():
        raise CronError(f"not a number: {text!r}")
    value = int(text)
    if not lo <= value <= hi:
        raise CronError(f"{value} is outside {lo}-{hi}")
    return value
