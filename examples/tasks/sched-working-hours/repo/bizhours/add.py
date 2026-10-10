"""Adding working time to a datetime."""

from datetime import datetime, timedelta


def add_working_minutes(cal, start, minutes):
    """Return the moment ``minutes`` of working time after ``start``."""
    if minutes < 0:
        raise ValueError("minutes must be >= 0")
    cur = cal.next_open(start)
    remaining = minutes
    while True:
        end = datetime.combine(cur.date(), cal.close)
        available = (end - cur).total_seconds() / 60
        if remaining <= available:
            return cur + timedelta(minutes=remaining)
        remaining -= available
        cur = cal.next_open(end)
