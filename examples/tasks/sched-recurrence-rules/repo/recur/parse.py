"""Text form of rules: ``FREQ=DAILY;INTERVAL=2;COUNT=5``."""

from datetime import date

from .rule import Rule


def parse_rule(text):
    if not text:
        raise ValueError("empty rule")
    fields = {}
    for part in text.split(";"):
        key, sep, value = part.partition("=")
        key = key.upper()
        if not sep or not value:
            raise ValueError(f"malformed segment {part!r}")
        if key in fields:
            raise ValueError(f"duplicate key {key}")
        fields[key] = value
    if "FREQ" not in fields:
        raise ValueError("FREQ is required")
    kwargs = {"freq": fields.pop("FREQ").upper()}
    if "INTERVAL" in fields:
        kwargs["interval"] = _int(fields.pop("INTERVAL"), "INTERVAL")
    if "COUNT" in fields:
        kwargs["count"] = _int(fields.pop("COUNT"), "COUNT")
    if "UNTIL" in fields:
        kwargs["until"] = _date(fields.pop("UNTIL"), "UNTIL")
    if fields:
        raise ValueError(f"unknown key(s): {', '.join(sorted(fields))}")
    return Rule(**kwargs)


def format_rule(rule):
    parts = [f"FREQ={rule.freq}"]
    if rule.interval != 1:
        parts.append(f"INTERVAL={rule.interval}")
    if rule.count is not None:
        parts.append(f"COUNT={rule.count}")
    if rule.until is not None:
        parts.append(f"UNTIL={rule.until.isoformat()}")
    return ";".join(parts)


def _int(value, name):
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer: {value!r}") from None


def _date(value, name):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be an ISO date: {value!r}") from None
