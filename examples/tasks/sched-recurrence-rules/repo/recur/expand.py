"""Expanding a rule into dates."""

from datetime import timedelta


def _raw(rule, start):
    """Candidate dates in increasing order, ignoring COUNT and UNTIL."""
    step = timedelta(days=rule.interval * (1 if rule.freq == "DAILY" else 7))
    current = start
    while True:
        yield current
        try:
            current = current + step
        except OverflowError:
            return


def occurrences(rule, start):
    """Lazily yield the dates of ``rule`` beginning at ``start``."""
    produced = 0
    for d in _raw(rule, start):
        if rule.until is not None and d > rule.until:
            return
        if rule.count is not None and produced >= rule.count:
            return
        produced += 1
        yield d


def between(rule, start, lo, hi):
    """Occurrences d with ``lo <= d <= hi`` (inclusive), as a list."""
    out = []
    for d in occurrences(rule, start):
        if d > hi:
            break
        if d >= lo:
            out.append(d)
    return out
