"""Descriptive statistics."""

import math


def percentile(values, p):
    """Nearest-rank percentile: the smallest value such that at least ``p`` percent of the values
    are less than or equal to it (``p`` in 0 < p <= 100).  For 4 values the 50th percentile is the
    2nd smallest, the 75th the 3rd."""
    if not values:
        raise ValueError("no values")
    if not 0 < p <= 100:
        raise ValueError("p must be in (0, 100]")
    ordered = sorted(values)
    rank = math.ceil(p / 100.0 * len(ordered))
    return ordered[rank - 1]


def mean(values):
    if not values:
        raise ValueError("no values")
    return sum(values) / len(values)


def describe(values):
    """Count, min, max, mean and the 50th / 95th / 99th percentile (``None`` for empty input)."""
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "p50": None, "p95": None, "p99": None}
    return {"count": len(values), "min": min(values), "max": max(values), "mean": mean(values),
            "p50": percentile(values, 50), "p95": percentile(values, 95), "p99": percentile(values, 99)}


def histogram(values, edges):
    """Counts per bin ``[edges[i], edges[i+1])``; the last bin also includes its upper edge.
    Values outside the edges are ignored."""
    counts = [0] * (len(edges) - 1)
    for value in values:
        for i in range(len(counts)):
            last = i == len(counts) - 1
            if edges[i] <= value < edges[i + 1] or (last and value == edges[i + 1]):
                counts[i] += 1
                break
    return counts
