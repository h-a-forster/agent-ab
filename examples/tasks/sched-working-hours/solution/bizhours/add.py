"""Adding working time to a datetime."""

from datetime import timedelta


def add_working_minutes(cal, start, minutes):
    """Return the moment ``minutes`` of working time after ``start``."""
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes < 0:
        raise ValueError("minutes must be a number >= 0")
    cal._check(start)
    if minutes == 0:
        return start
    cur = cal.next_open(start)
    remaining = minutes
    while True:
        end = next(e for s, e in cal.windows_on(cur.date()) if s <= cur < e)
        available = (end - cur).total_seconds() / 60
        if remaining <= available:
            return cur + timedelta(minutes=remaining)
        remaining -= available
        cur = cal.next_open(end)
