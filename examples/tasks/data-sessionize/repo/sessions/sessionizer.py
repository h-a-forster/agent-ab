"""Group events into sessions."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .models import Event, Session


def sessionize(events, gap: timedelta = timedelta(minutes=30)) -> list[Session]:
    """Split each user's events into sessions separated by gaps of ``gap`` or more."""
    by_user: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        by_user[event.user].append(event)
    sessions: list[Session] = []
    counter = 0
    for user, items in by_user.items():
        items.sort(key=lambda e: e.ts)
        current = [items[0]]
        for event in items[1:]:
            if event.ts - current[-1].ts >= gap:
                counter += 1
                sessions.append(_make(f"s{counter}", user, current))
                current = []
            current.append(event)
        counter += 1
        sessions.append(_make(f"s{counter}", user, current))
    sessions.sort(key=lambda s: s.start)
    return sessions


def _make(session_id: str, user: str, events: list[Event]) -> Session:
    return Session(session_id, user, events[0].ts, events[-1].ts, tuple(events))
