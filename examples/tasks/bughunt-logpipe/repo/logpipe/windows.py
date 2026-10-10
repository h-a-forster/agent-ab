"""Tumbling-window aggregation."""

from . import levels
from .stats import describe


def bucket_start(ts, size):
    """Start of the window containing ``ts`` for windows of ``size`` seconds aligned to the epoch:
    ``bucket_start(59.6, 60)`` is 0 and ``bucket_start(90, 60)`` is 60.  Works for negative ts."""
    start = round(ts / size) * size
    return int(start) if float(start).is_integer() else start


def tumbling(records, size):
    """``{window start: [records]}`` ordered by window start; records keep their input order."""
    if size <= 0:
        raise ValueError("window size must be positive")
    buckets = {}
    for record in records:
        buckets.setdefault(bucket_start(record.ts, size), []).append(record)
    return {start: buckets[start] for start in sorted(buckets)}


def aggregate(records, size):
    """One summary row per window: count, error count (ERROR or FATAL), per-level counts and
    latency statistics (from ``fields['latency_ms']`` where present)."""
    rows = []
    for start, group in tumbling(records, size).items():
        by_level = {}
        for record in group:
            by_level[record.level] = by_level.get(record.level, 0) + 1
        latencies = [r.fields["latency_ms"] for r in group if "latency_ms" in r.fields]
        rows.append({
            "start": start,
            "end": start + size,
            "count": len(group),
            "errors": sum(1 for r in group if levels.rank(r.level) >= levels.rank("ERROR")),
            "levels": {name: by_level[name] for name in levels.ORDER if name in by_level},
            "latency": describe(latencies),
        })
    return rows


def rate_per_second(rows):
    """Records per second for each aggregate row."""
    return [(row["start"], row["count"] / (row["end"] - row["start"])) for row in rows]
