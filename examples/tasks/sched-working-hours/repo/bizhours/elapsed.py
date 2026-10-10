"""Working time between two datetimes."""

from datetime import datetime, timedelta


def working_minutes_between(cal, a, b):
    """Minutes of working time in [a, b); negative if ``b`` is before ``a``."""
    if b < a:
        return -working_minutes_between(cal, b, a)
    total = 0.0
    day = a.date()
    while day <= b.date():
        if day.weekday() in cal.workdays:
            lo = max(a, datetime.combine(day, cal.open))
            hi = min(b, datetime.combine(day, cal.close))
            if hi > lo:
                total += (hi - lo).total_seconds() / 60
        day += timedelta(days=1)
    return total
