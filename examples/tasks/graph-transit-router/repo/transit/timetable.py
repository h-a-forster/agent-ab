"""Timetable data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Connection:
    src: str
    dst: str
    dep: int
    arr: int
    trip: str

    def __post_init__(self):
        if self.src == self.dst:
            raise ValueError("connection must go between two different stations")
        if self.arr <= self.dep:
            raise ValueError("connection must arrive after it departs")


class Timetable:
    def __init__(self, connections):
        self.connections = tuple(sorted(connections, key=lambda c: (c.dep, c.arr, c.trip, c.src, c.dst)))
