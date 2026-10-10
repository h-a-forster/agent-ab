"""Finding matching times."""

from __future__ import annotations

from datetime import datetime, timedelta

from .expr import CronError, CronExpr


def _weekday(dt: datetime) -> int:
    return (dt.weekday() + 1) % 7  # Sunday = 0


def matches(expr: CronExpr, dt: datetime) -> bool:
    """True if the minute containing ``dt`` matches ``expr``."""
    return (
        dt.minute in expr.minutes
        and dt.hour in expr.hours
        and dt.day in expr.days
        and dt.month in expr.months
        and _weekday(dt) in expr.weekdays
    )


def next_after(expr: CronExpr, dt: datetime) -> datetime:
    """The first matching minute strictly after ``dt`` (searches up to a year ahead)."""
    candidate = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        if matches(expr, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise CronError("no matching time within a year")


def upcoming(expr: CronExpr, start: datetime, count: int) -> list[datetime]:
    """The next ``count`` matching minutes after ``start``."""
    out = []
    current = start
    for _ in range(count):
        current = next_after(expr, current)
        out.append(current)
    return out
