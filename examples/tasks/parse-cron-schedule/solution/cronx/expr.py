"""The :class:`CronExpr` class."""

from __future__ import annotations

from dataclasses import dataclass

from .fields import DOW_NAMES, MONTH_NAMES, CronError, is_star, parse_field

__all__ = ["CronError", "CronExpr"]

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}


@dataclass(frozen=True)
class CronExpr:
    minutes: frozenset
    hours: frozenset
    days: frozenset  # day of month, 1-31
    months: frozenset  # 1-12
    weekdays: frozenset  # 0-6, Sunday = 0
    days_star: bool = True
    weekdays_star: bool = True

    @classmethod
    def parse(cls, text: str) -> "CronExpr":
        stripped = text.strip()
        if stripped.startswith("@"):
            try:
                stripped = MACROS[stripped.lower()]
            except KeyError:
                raise CronError(f"unknown macro {stripped!r}") from None
        parts = stripped.split()
        if len(parts) != 5:
            raise CronError(f"expected 5 fields, got {len(parts)}")
        minute, hour, dom, month, dow = parts
        weekdays = parse_field(dow, 0, 7, DOW_NAMES, allow_question=True)
        return cls(
            parse_field(minute, 0, 59),
            parse_field(hour, 0, 23),
            parse_field(dom, 1, 31, allow_question=True),
            parse_field(month, 1, 12, MONTH_NAMES),
            frozenset(d % 7 for d in weekdays),
            is_star(dom),
            is_star(dow),
        )
