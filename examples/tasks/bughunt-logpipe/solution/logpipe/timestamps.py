"""Timestamp parsing (to UTC epoch seconds) and formatting."""

import calendar
import re
import time

from .errors import TimestampError

_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
_ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?\s*(Z|z|[+-]\d{2}(?::?\d{2})?)?$"
)
_CLF = re.compile(r"^(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-]\d{4})$")
_MONTHS = {name: i for i, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def parse_offset(text):
    """Seconds east of UTC for ``Z``, ``+05:30``, ``-0800`` or ``+02``.  ``None`` means UTC."""
    if text is None or text in ("Z", "z"):
        return 0
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    hours = int(digits[:2])
    minutes = int(digits[2:4]) if len(digits) > 2 else 0
    if hours > 23 or minutes > 59:
        raise TimestampError("bad UTC offset %r" % text)
    return sign * (hours * 3600 + minutes * 60)


def _to_epoch(year, month, day, hour, minute, second, offset):
    if not (1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60 and second < 61):
        raise TimestampError("timestamp field out of range")
    local = calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0))
    return local - offset


def parse_timestamp(text):
    """UTC epoch seconds for an ISO-8601 / common-log / numeric timestamp.

    ``2024-03-10T12:00:00+05:30`` is 06:30:00 UTC: a positive offset means the local clock is
    *ahead* of UTC, so it is subtracted.  Timestamps without an offset are taken as UTC.
    Fractional seconds are kept (the result is then a float), plain numbers are epoch seconds.
    """
    text = str(text).strip()
    if _NUMBER.match(text):
        return float(text) if "." in text else int(text)
    m = _ISO.match(text)
    if m:
        year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
        epoch = _to_epoch(year, month, day, hour, minute, second, parse_offset(m.group(8)))
        return epoch + float(m.group(7)) if m.group(7) else epoch
    m = _CLF.match(text)
    if m:
        month = _MONTHS.get(m.group(2).lower())
        if month is None:
            raise TimestampError("unknown month %r" % m.group(2))
        return _to_epoch(int(m.group(3)), month, int(m.group(1)), int(m.group(4)), int(m.group(5)),
                         int(m.group(6)), parse_offset(m.group(7)))
    raise TimestampError("unsupported timestamp %r" % text)


def format_epoch(ts):
    """``1710000000`` -> ``"2024-03-09T16:00:00Z"`` (whole seconds, UTC)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(ts // 1)))
