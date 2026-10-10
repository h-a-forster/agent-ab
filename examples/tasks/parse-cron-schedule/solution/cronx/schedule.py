"""Finding matching times."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .expr import CronError, CronExpr


def _weekday(d: date) -> int:
    return (d.weekday() + 1) % 7  # Sunday = 0


def _day_ok(expr: CronExpr, d: date) -> bool:
    if d.month not in expr.months:
        return False
    dom_ok = d.day in expr.days
    dow_ok = _weekday(d) in expr.weekdays
    if expr.days_star or expr.weekdays_star:
        return dom_ok and dow_ok
    return dom_ok or dow_ok


def matches(expr: CronExpr, dt: datetime) -> bool:
    """True if the minute containing ``dt`` matches ``expr`` (seconds are ignored)."""
    return dt.minute in expr.minutes and dt.hour in expr.hours and _day_ok(expr, dt.date())


def next_after(expr: CronExpr, dt: datetime, max_years: int = 10) -> datetime:
    """The first matching minute strictly after ``dt``; ``CronError`` if none in ``max_years``."""
    first = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    minutes = sorted(expr.minutes)
    hours = sorted(expr.hours)
    day = first.date()
    last_year = dt.year + max_years
    while day.year <= last_year:
        if _day_ok(expr, day):
            h0, m0 = (first.hour, first.minute) if day == first.date() else (0, 0)
            for h in hours:
                if h < h0:
                    continue
                for m in minutes:
                    if h == h0 and m < m0:
                        continue
                    return datetime.combine(day, time(h, m), tzinfo=dt.tzinfo)
        day += timedelta(days=1)
    raise CronError(f"no matching time within {max_years} years")


def upcoming(expr: CronExpr, start: datetime, count: int) -> list[datetime]:
    """The next ``count`` matching minutes after ``start``."""
    if count < 0:
        raise ValueError("count must not be negative")
    out = []
    current = start
    for _ in range(count):
        current = next_after(expr, current)
        out.append(current)
    return out
