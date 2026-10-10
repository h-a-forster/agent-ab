"""Line parsers: common log format, JSON lines and logfmt."""

import json
import re

from . import levels
from .errors import ParseError, TimestampError
from .records import Record
from .timestamps import parse_timestamp

_CLF = re.compile(
    r'^(?P<ip>\S+) \S+ (?P<user>\S+) \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-)(?: (?P<latency>\d+(?:\.\d+)?))?$'
)
_LOGFMT = re.compile(r'(\w[\w.-]*)=("(?:[^"\\]|\\.)*"|\S*)')
TIME_KEYS = ("ts", "timestamp", "time", "@timestamp")
LEVEL_KEYS = ("level", "severity", "lvl")
MSG_KEYS = ("msg", "message")


def parse_clf(line):
    m = _CLF.match(line.strip())
    if not m:
        raise ParseError("not a common-log-format line")
    status = int(m.group("status"))
    fields = {
        "ip": m.group("ip"), "user": None if m.group("user") == "-" else m.group("user"),
        "method": m.group("method"), "path": m.group("path"), "status": status,
        "bytes": 0 if m.group("bytes") == "-" else int(m.group("bytes")),
    }
    if m.group("latency") is not None:
        fields["latency_ms"] = float(m.group("latency"))
    return Record(parse_timestamp(m.group("time")), levels.from_status(status),
                  "%s %s" % (m.group("method"), m.group("path")), host=m.group("ip"), fields=fields)


def _pick(data, keys):
    for key in keys:
        if key in data:
            return data.pop(key)
    return None


def _from_mapping(data):
    data = dict(data)
    raw_ts = _pick(data, TIME_KEYS)
    if raw_ts is None:
        raise ParseError("record has no timestamp")
    level = levels.parse_level(_pick(data, LEVEL_KEYS), default="INFO")
    msg = _pick(data, MSG_KEYS)
    host = data.pop("host", None)
    return Record(parse_timestamp(raw_ts), level, "" if msg is None else str(msg), host=host, fields=data)


def parse_json(line):
    try:
        data = json.loads(line)
    except ValueError as exc:
        raise ParseError("invalid JSON: %s" % exc) from None
    if not isinstance(data, dict):
        raise ParseError("JSON line is not an object")
    return _from_mapping(data)


def _unquote(value):
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


def _convert(value):
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def parse_logfmt(line):
    pairs = _LOGFMT.findall(line)
    if not pairs:
        raise ParseError("not a logfmt line")
    data = {}
    for key, value in pairs:
        quoted = value.startswith('"')
        text = _unquote(value)
        data[key] = text if quoted or key in TIME_KEYS + MSG_KEYS + LEVEL_KEYS + ("host",) else _convert(text)
    return _from_mapping(data)


def detect_format(line):
    stripped = line.strip()
    if stripped.startswith("{"):
        return "json"
    if re.search(r'(^|\s)(ts|time|timestamp|level)=', stripped):
        return "logfmt"
    return "clf"


PARSERS = {"clf": parse_clf, "json": parse_json, "logfmt": parse_logfmt}


def parse_line(line, fmt="auto", lineno=None):
    """Parse one line into a Record (``fmt`` is ``auto``, ``clf``, ``json`` or ``logfmt``)."""
    if fmt == "auto":
        fmt = detect_format(line)
    parser = PARSERS.get(fmt)
    if parser is None:
        raise ParseError("unknown format %r" % (fmt,))
    try:
        record = parser(line)
    except TimestampError as exc:
        raise ParseError("bad timestamp: %s" % exc) from None
    record.raw = line.rstrip("\n")
    record.lineno = lineno
    return record
