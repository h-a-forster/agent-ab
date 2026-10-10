"""Daily statistics over sessions."""

from __future__ import annotations

from collections import defaultdict

from .models import DayStats, Session


def daily_report(sessions: list[Session]) -> list[DayStats]:
    """One row per UTC day (the day the session ended), oldest first."""
    buckets: dict = defaultdict(list)
    for s in sessions:
        buckets[s.end.date()].append(s)
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
                total_value=sum(e.value for s in group for e in s.events),
            )
        )
    return rows
