"""Daily statistics over sessions."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .models import DayStats, Session


def daily_report(sessions: list[Session], utc_offset: timedelta = timedelta(0)) -> list[DayStats]:
    """One row per local day (the day the session started), oldest first."""
    if not -timedelta(hours=24) < utc_offset < timedelta(hours=24):
        raise ValueError("utc_offset must be within +/-24 hours")
    buckets: dict = defaultdict(list)
    for s in sessions:
        buckets[(s.start + utc_offset).date()].append(s)
    rows = []
    for day in sorted(buckets):
        group = buckets[day]
        events = sum(s.count for s in group)
        rows.append(
            DayStats(
                day=day,
                sessions=len(group),
                users=len({s.user for s in group}),
                events=events,
                total_seconds=sum(s.duration.total_seconds() for s in group),
                avg_events=events / len(group),
                total_value=float(sum(e.value for s in group for e in s.events)),
            )
        )
    return rows
