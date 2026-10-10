"""The Rule value object."""

from dataclasses import dataclass
from datetime import date

FREQS = ("DAILY", "WEEKLY")


@dataclass(frozen=True)
class Rule:
    freq: str
    interval: int = 1
    count: int | None = None
    until: date | None = None

    def __post_init__(self):
        if self.freq not in FREQS:
            raise ValueError(f"unsupported FREQ {self.freq!r}")
        if not isinstance(self.interval, int) or self.interval < 1:
            raise ValueError("INTERVAL must be a positive integer")
        if self.count is not None and (not isinstance(self.count, int) or self.count < 1):
            raise ValueError("COUNT must be a positive integer")
        if self.count is not None and self.until is not None:
            raise ValueError("COUNT and UNTIL are mutually exclusive")
