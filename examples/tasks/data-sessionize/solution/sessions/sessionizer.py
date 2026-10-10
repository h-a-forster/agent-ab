"""Group events into sessions."""

from __future__ import annotations

from datetime import timedelta

from .models import Event, Session


def sessionize(
    events,
    gap: timedelta = timedelta(minutes=30),
    max_duration: timedelta | None = None,
    types=None,
) -> list[Session]:
    """Split each user's events into sessions (see the task description for the rules)."""
    if gap <= timedelta(0):
        raise ValueError("gap must be positive")
    if max_duration is not None and max_duration <= timedelta(0):
        raise ValueError("max_duration must be positive")
    wanted = None if types is None else set(types)
    seen: set = set()
    by_user: dict[str, list[Event]] = {}
    for event in events:
        if wanted is not None and event.type not in wanted:
            continue
        key = (event.user, event.ts, event.type)
        if key in seen:
            continue
        seen.add(key)
        by_user.setdefault(event.user, []).append(event)
    sessions: list[Session] = []
    for user, items in by_user.items():
        items.sort(key=lambda e: e.ts)
        number = 0
        current: list[Event] = []
        for event in items:
            if current and (
                event.ts - current[-1].ts > gap
                or (max_duration is not None and event.ts - current[0].ts > max_duration)
            ):
                number += 1
                sessions.append(_make(f"{user}#{number}", user, current))
                current = []
            current.append(event)
        number += 1
        sessions.append(_make(f"{user}#{number}", user, current))
    sessions.sort(key=lambda s: (s.start, s.user))
    return sessions


def _make(session_id: str, user: str, events: list[Event]) -> Session:
    return Session(session_id, user, events[0].ts, events[-1].ts, tuple(events))
