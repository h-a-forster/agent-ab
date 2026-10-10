"""Expanding a rule into dates."""

import calendar
from datetime import date, timedelta


def _daily(rule, start):
    step = timedelta(days=rule.interval)
    current = start
    while True:
        yield current
        current += step


def _weekly(rule, start):
    days = sorted(set(rule.byday)) or [start.weekday()]
    week0 = start - timedelta(days=start.weekday())
    k = 0
    while True:
        monday = week0 + timedelta(weeks=rule.interval * k)
        for wd in days:
            d = monday + timedelta(days=wd)
            if d >= start:
                yield d
        k += 1


def _clamped(year, month, day):
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _monthly(rule, start):
    k = 0
    while True:
        year, month0 = divmod(start.month - 1 + rule.interval * k, 12)
        yield _clamped(start.year + year, month0 + 1, start.day)
        k += 1


def _yearly(rule, start):
    k = 0
    while True:
        yield _clamped(start.year + rule.interval * k, start.month, start.day)
        k += 1


_GENERATORS = {"DAILY": _daily, "WEEKLY": _weekly, "MONTHLY": _monthly, "YEARLY": _yearly}


def _raw(rule, start):
    try:
        yield from _GENERATORS[rule.freq](rule, start)
    except (OverflowError, ValueError):
        return  # ran past date.max


def occurrences(rule, start):
    """Lazily yield the dates of ``rule`` beginning at ``start``.

    COUNT limits the generated occurrences *before* EXDATE removal.
    """
    produced = 0
    for d in _raw(rule, start):
        if rule.until is not None and d > rule.until:
            return
        if rule.count is not None and produced >= rule.count:
            return
        produced += 1
        if d in rule.exdates:
            continue
        yield d


def between(rule, start, lo, hi):
    out = []
    for d in occurrences(rule, start):
        if d > hi:
            break
        if d >= lo:
            out.append(d)
    return out
