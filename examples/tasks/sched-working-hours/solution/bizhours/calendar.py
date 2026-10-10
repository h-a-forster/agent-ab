"""WorkCalendar: per-weekday working windows plus holidays."""

from datetime import date, datetime, time, timedelta


class WorkCalendar:
    def __init__(self, open=time(9, 0), close=time(17, 0), workdays=(0, 1, 2, 3, 4), *,
                 windows=None, holidays=(), observe_weekends=False):
        if windows is None:
            if not open < close:
                raise ValueError("open must be before close")
            windows = {wd: [(open, close)] for wd in workdays}
        self._windows = {}
        for wd, spans in windows.items():
            if not isinstance(wd, int) or not 0 <= wd <= 6:
                raise ValueError(f"bad weekday {wd!r}")
            merged = []
            for lo, hi in sorted(spans):
                if not lo < hi:
                    raise ValueError("window open must be before close")
                if merged and lo < merged[-1][1]:
                    raise ValueError("overlapping windows")
                if merged and lo == merged[-1][1]:
                    merged[-1] = (merged[-1][0], hi)
                else:
                    merged.append((lo, hi))
            if merged:
                self._windows[wd] = tuple(merged)
        if not self._windows:
            raise ValueError("calendar has no working time")
        days = set()
        for h in holidays:
            if observe_weekends and h.weekday() == 5:
                h = h - timedelta(days=1)
            elif observe_weekends and h.weekday() == 6:
                h = h + timedelta(days=1)
            days.add(h)
        self.holidays = frozenset(days)
        # legacy attributes
        self.open, self.close = open, close
        self.workdays = frozenset(self._windows)

    @staticmethod
    def _check(dt):
        if dt.tzinfo is not None:
            raise ValueError("timezone-aware datetimes are not supported")

    def windows_on(self, day):
        """Working windows of a calendar date as (start, end) datetimes, ascending."""
        if day in self.holidays:
            return []
        return [(datetime.combine(day, lo), datetime.combine(day, hi))
                for lo, hi in self._windows.get(day.weekday(), ())]

    def is_working(self, dt):
        self._check(dt)
        return any(s <= dt < e for s, e in self.windows_on(dt.date()))

    def next_open(self, dt):
        self._check(dt)
        day = dt.date()
        while True:
            for s, e in self.windows_on(day):
                if dt < e:
                    return max(dt, s)
            day += timedelta(days=1)
