"""Timetable data."""

from dataclasses import dataclass


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@dataclass(frozen=True)
class Connection:
    src: str
    dst: str
    dep: int
    arr: int
    trip: str

    def __post_init__(self):
        if not (_is_int(self.dep) and _is_int(self.arr)):
            raise ValueError("times must be integer minutes")
        if self.src == self.dst:
            raise ValueError("connection must go between two different stations")
        if self.arr <= self.dep:
            raise ValueError("connection must arrive after it departs")


class Timetable:
    def __init__(self, connections, transfers=None, default_transfer=0):
        if not _is_int(default_transfer) or default_transfer < 0:
            raise ValueError("default_transfer must be a non-negative integer")
        self.transfers = dict(transfers or {})
        for station, minutes in self.transfers.items():
            if not _is_int(minutes) or minutes < 0:
                raise ValueError(f"bad transfer time for {station!r}")
        self.default_transfer = default_transfer
        self.connections = tuple(sorted(connections, key=lambda c: (c.dep, c.arr, c.trip, c.src, c.dst)))

    def transfer_time(self, station):
        """Minimum minutes needed to change trips at ``station``."""
        return self.transfers.get(station, self.default_transfer)
