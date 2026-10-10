"""Set operations on lists of intervals."""

from .model import Interval


def merge(intervals):
    """Union of the intervals as a sorted list of disjoint, non-touching intervals."""
    ordered = sorted(intervals, key=lambda i: (i.lo, i.hi))
    out = []
    for iv in ordered:
        if out and iv.lo <= out[-1].hi:
            if iv.hi > out[-1].hi:
                out[-1] = Interval(out[-1].lo, iv.hi)
        else:
            out.append(iv)
    return out


def intersect(a, b):
    """Overlap of two intervals, or None when they share no point."""
    lo = max(a.lo, b.lo)
    hi = min(a.hi, b.hi)
    if lo < hi:
        return Interval(lo, hi)
    return None


def subtract(a, b):
    """Parts of ``a`` not covered by ``b``, as a sorted list of 0, 1 or 2 intervals."""
    out = []
    if b.lo > a.lo:
        left_hi = min(a.hi, b.lo)
        out.append(Interval(a.lo, left_hi))
    if b.hi < a.hi:
        right_lo = max(a.lo, b.hi)
        out.append(Interval(right_lo, a.hi))
    return out


def gaps(intervals, window):
    """Parts of ``window`` not covered by any of ``intervals``."""
    pieces = [window]
    for cover in merge(intervals):
        nxt = []
        for piece in pieces:
            nxt.extend(subtract(piece, cover))
        pieces = nxt
    return pieces


def total_length(intervals):
    """Total measure covered by the union of the intervals."""
    return sum(iv.length for iv in merge(intervals))
