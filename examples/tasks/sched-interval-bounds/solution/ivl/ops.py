"""Set operations on lists of intervals."""

from .model import Interval


def _maybe(lo_b, hi_b):
    return Interval.from_bounds(lo_b, hi_b) if lo_b < hi_b else None


def merge(intervals):
    """Union of the intervals as a sorted list of disjoint, non-adjacent intervals."""
    ordered = sorted(intervals, key=lambda i: (i.lo_b, i.hi_b))
    out = []
    for iv in ordered:
        if out and iv.lo_b <= out[-1].hi_b:
            if iv.hi_b > out[-1].hi_b:
                out[-1] = Interval.from_bounds(out[-1].lo_b, iv.hi_b)
        else:
            out.append(iv)
    return out


def intersect(a, b):
    return _maybe(max(a.lo_b, b.lo_b), min(a.hi_b, b.hi_b))


def subtract(a, b):
    """Parts of ``a`` not covered by ``b``; boundaries flip (b's lower edge ends the left part)."""
    out = []
    left = _maybe(a.lo_b, min(a.hi_b, b.lo_b))
    if left:
        out.append(left)
    right = _maybe(max(a.lo_b, b.hi_b), a.hi_b)
    if right:
        out.append(right)
    return out


def gaps(intervals, window):
    pieces = [window]
    for cover in merge(intervals):
        nxt = []
        for piece in pieces:
            nxt.extend(subtract(piece, cover))
        pieces = nxt
    return pieces


def total_length(intervals):
    return sum(iv.length for iv in merge(intervals))
