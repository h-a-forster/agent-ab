"""Data classes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class Event:
    ts: datetime  # timezone-aware, UTC
    user: str
    type: str = "event"
    value: float = 0.0


@dataclass(frozen=True)
class Session:
    id: str
    user: str
    start: datetime
    end: datetime
    events: tuple[Event, ...]

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def count(self) -> int:
        return len(self.events)


@dataclass(frozen=True)
class DayStats:
    day: date
    sessions: int
    users: int
    events: int
    total_seconds: float
    avg_events: float
    total_value: float
