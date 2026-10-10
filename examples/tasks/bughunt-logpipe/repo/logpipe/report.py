"""Text summaries."""

from . import levels
from .timestamps import format_epoch


def level_counts(records):
    """``{level: count}`` in severity order, only levels that occur."""
    counts = {}
    for record in records:
        counts[record.level] = counts.get(record.level, 0) + 1
    return {name: counts[name] for name in levels.ORDER if name in counts}


def top_values(records, field, n=3):
    """The ``n`` most frequent values of a field as ``(value, count)``; ties by value."""
    counts = {}
    for record in records:
        value = record.get(field)
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return ranked[:n]


def format_result(result):
    lines = ["read %d, parsed %d, written %d" % (result.read, result.parsed, result.written),
             "filtered %d, duplicates %d, errors %d" % (result.filtered, result.duplicates, len(result.errors))]
    for lineno, message in result.errors:
        lines.append("  line %d: %s" % (lineno, message))
    return "\n".join(lines)


def format_windows(rows):
    """One line per window: ``<start ISO> count=<n> errors=<n>``."""
    return "\n".join("%s count=%d errors=%d" % (format_epoch(row["start"]), row["count"], row["errors"]) for row in rows)
