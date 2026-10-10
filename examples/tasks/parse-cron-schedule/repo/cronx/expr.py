"""The :class:`CronExpr` class."""

from __future__ import annotations

from dataclasses import dataclass

from .fields import CronError, parse_field

__all__ = ["CronError", "CronExpr"]


@dataclass(frozen=True)
class CronExpr:
    minutes: frozenset
    hours: frozenset
    days: frozenset  # day of month, 1-31
    months: frozenset  # 1-12
    weekdays: frozenset  # 0-6, Sunday = 0

    @classmethod
    def parse(cls, text: str) -> "CronExpr":
        parts = text.split()
        if len(parts) != 5:
            raise CronError(f"expected 5 fields, got {len(parts)}")
        minute, hour, dom, month, dow = parts
        return cls(
            parse_field(minute, 0, 59),
            parse_field(hour, 0, 23),
            parse_field(dom, 1, 31),
            parse_field(month, 1, 12),
            parse_field(dow, 0, 6),
        )
