"""The Interval value type: always half-open, ``[lo, hi)``."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float

    def __post_init__(self):
        if not self.lo < self.hi:
            raise ValueError(f"empty interval: lo={self.lo!r} hi={self.hi!r}")

    @property
    def length(self):
        return self.hi - self.lo

    def contains(self, point):
        return self.lo <= point < self.hi

    def overlaps(self, other):
        return self.lo < other.hi and other.lo < self.hi

    def __str__(self):
        return f"[{self.lo}, {self.hi})"
