"""Working time between two datetimes."""

from datetime import timedelta


def working_minutes_between(cal, a, b):
    """Minutes of working time in [a, b); negative if ``b`` is before ``a``."""
    cal._check(a)
    cal._check(b)
    if b < a:
        return -working_minutes_between(cal, b, a)
    total = 0.0
    day = a.date()
    while day <= b.date():
        for s, e in cal.windows_on(day):
            lo, hi = max(a, s), min(b, e)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60
        day += timedelta(days=1)
    return total
