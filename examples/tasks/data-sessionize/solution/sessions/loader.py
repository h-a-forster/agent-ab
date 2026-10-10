"""Read events from JSON lines."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from .models import Event


class EventError(ValueError):
    """A log line is not a valid event. ``line`` is its 1-based position in the input."""

    def __init__(self, line: int, message: str) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


def parse_ts(raw) -> datetime:
    """Parse an ISO-8601 string or an epoch number (seconds) into an aware UTC datetime."""
    if isinstance(raw, bool):
        raise ValueError("timestamp must be a string or a number")
    if isinstance(raw, (int, float)):
        if not math.isfinite(raw):
            raise ValueError("timestamp must be finite")
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise ValueError("timestamp out of range") from None
    if isinstance(raw, str):
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise ValueError("timestamp must be a string or a number")


def parse_event(obj, line: int) -> Event:
    if not isinstance(obj, dict):
        raise EventError(line, "event must be a JSON object")
    try:
        ts = parse_ts(obj["ts"])
    except (KeyError, ValueError, OverflowError) as exc:
        raise EventError(line, f"bad timestamp: {exc!r}") from None
    user = obj.get("user")
    if not isinstance(user, str) or not user:
        raise EventError(line, "missing user")
    etype = obj.get("type", "event")
    if not isinstance(etype, str) or not etype:
        raise EventError(line, "bad type")
    value = obj.get("value", 0.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EventError(line, "bad value")
    return Event(ts, user, etype, value)


def _records(lines):
    for number, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        try:
            obj = json.loads(text)
        except ValueError as exc:
            yield number, None, EventError(number, f"invalid JSON: {exc}")
            continue
        try:
            yield number, parse_event(obj, number), None
        except EventError as err:
            yield number, None, err


def load_events(lines) -> list[Event]:
    """Parse JSON-lines ``lines`` (blank lines are skipped); raises ``EventError`` on bad input."""
    events = []
    for _, event, err in _records(lines):
        if err is not None:
            raise err
        events.append(event)
    return events


def load_lenient(lines) -> tuple[list[Event], list[EventError]]:
    """Like :func:`load_events` but collects the bad lines instead of raising."""
    events, errors = [], []
    for _, event, err in _records(lines):
        if err is not None:
            errors.append(err)
        else:
            events.append(event)
    return events, errors
