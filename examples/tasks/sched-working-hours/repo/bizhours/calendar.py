"""WorkCalendar: one daily window on a set of weekdays."""

from datetime import datetime, time, timedelta


class WorkCalendar:
    def __init__(self, open=time(9, 0), close=time(17, 0), workdays=(0, 1, 2, 3, 4)):
        if not open < close:
            raise ValueError("open must be before close")
        self.open = open
        self.close = close
        self.workdays = frozenset(workdays)

    def is_working(self, dt):
        return dt.weekday() in self.workdays and self.open <= dt.time() < self.close

    def next_open(self, dt):
        """``dt`` itself if it is working time, else the next moment working time starts."""
        day = dt.date()
        while True:
            if day.weekday() in self.workdays:
                start = datetime.combine(day, self.open)
                end = datetime.combine(day, self.close)
                if dt < end:
                    return max(dt, start)
            day += timedelta(days=1)
