"""Read events from JSON lines."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .models import Event


class EventError(ValueError):
    """A log line is not a valid event. ``line`` is its 1-based position in the input."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


def parse_ts(raw) -> datetime:
    """Parse a timestamp such as ``2024-03-01T10:00:00Z`` into an aware UTC datetime."""
    if not isinstance(raw, str):
        raise ValueError("timestamp must be a string")
    return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_event(obj, line: int) -> Event:
    if not isinstance(obj, dict):
        raise EventError(line, "event must be a JSON object")
    try:
        ts = parse_ts(obj["ts"])
    except (KeyError, ValueError) as exc:
        raise EventError(line, f"bad timestamp: {exc}") from None
    user = obj.get("user")
    if not isinstance(user, str) or not user:
        raise EventError(line, "missing user")
    return Event(ts, user, obj.get("type", "event"), obj.get("value", 0.0))


def load_events(lines) -> list[Event]:
    """Parse JSON-lines ``lines`` (blank lines are skipped); raises ``EventError`` on bad input."""
    events = []
    for number, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        try:
            obj = json.loads(text)
        except ValueError as exc:
            raise EventError(number, f"invalid JSON: {exc}") from None
        events.append(parse_event(obj, number))
    return events
