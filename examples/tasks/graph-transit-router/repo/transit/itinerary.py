"""Itineraries."""

from dataclasses import dataclass


def format_time(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Leg:
    trip: str
    src: str
    dst: str
    dep: int
    arr: int


@dataclass(frozen=True)
class Itinerary:
    legs: tuple
    departure: int
    arrival: int

    @property
    def transfers(self):
        return max(0, len(self.legs) - 1)

    def describe(self):
        return "\n".join(
            f"{format_time(l.dep)} {l.src} -> {format_time(l.arr)} {l.dst} [{l.trip}]" for l in self.legs
        )
