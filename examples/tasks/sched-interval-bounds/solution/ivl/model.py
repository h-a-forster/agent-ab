"""The Interval value type with optionally open or closed bounds."""

from dataclasses import dataclass

# Boundaries are positions on the line *between* points: (value, -1) is just before
# ``value`` and (value, +1) just after it. A closed lower bound or an open upper bound
# sits just before its value; an open lower bound or closed upper bound just after it.


@dataclass(frozen=True)
class Interval:
    lo: float
    hi: float
    lo_closed: bool = True
    hi_closed: bool = False

    def __post_init__(self):
        if not self.lo_b < self.hi_b:
            raise ValueError(f"empty interval: {self.lo!r}..{self.hi!r}")

    @property
    def lo_b(self):
        return (self.lo, -1 if self.lo_closed else 1)

    @property
    def hi_b(self):
        return (self.hi, 1 if self.hi_closed else -1)

    @classmethod
    def from_bounds(cls, lo_b, hi_b):
        """Build from boundary positions; ValueError if they enclose no point."""
        return cls(lo_b[0], hi_b[0], lo_b[1] == -1, hi_b[1] == 1)

    @property
    def length(self):
        return self.hi - self.lo

    def contains(self, point):
        return self.lo_b < (point, 0) < self.hi_b

    def overlaps(self, other):
        return max(self.lo_b, other.lo_b) < min(self.hi_b, other.hi_b)

    def __str__(self):
        left = "[" if self.lo_closed else "("
        right = "]" if self.hi_closed else ")"
        return f"{left}{self.lo}, {self.hi}{right}"
