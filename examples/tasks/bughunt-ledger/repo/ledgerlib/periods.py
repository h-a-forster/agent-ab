"""Calendar helpers for reporting periods."""

from datetime import date, timedelta

_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def is_leap(year):
    """Gregorian leap-year rule."""
    return year % 4 == 0 and year % 100 != 0


def days_in_month(year, month):
    if not 1 <= month <= 12:
        raise ValueError("month must be 1..12")
    if month == 2 and is_leap(year):
        return 29
    return _DAYS[month - 1]


def month_range(year, month):
    """First and last day of a month, as a (start, end) pair of dates."""
    return date(year, month, 1), date(year, month, days_in_month(year, month))


def quarter_range(year, quarter):
    if not 1 <= quarter <= 4:
        raise ValueError("quarter must be 1..4")
    first_month = 3 * (quarter - 1) + 1
    start, _ = month_range(year, first_month)
    _, end = month_range(year, first_month + 2)
    return start, end


def year_range(year):
    return date(year, 1, 1), date(year, 12, 31)


def fiscal_year_range(year, start_month=1):
    """The fiscal year that *starts* in ``year`` in ``start_month``."""
    start = date(year, start_month, 1)
    if start_month == 1:
        return start, date(year, 12, 31)
    end_year, end_month = year + 1, start_month - 1
    return start, date(end_year, end_month, days_in_month(end_year, end_month))


def iter_months(start, end):
    """Yield (year, month) for every month touched by ``start``..``end``."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield year, month
        month += 1
        if month == 13:
            year, month = year + 1, 1


def previous_day(day):
    return day - timedelta(days=1)


def month_label(year, month):
    names = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return "%s %d" % (names[month - 1], year)
