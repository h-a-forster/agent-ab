"""Text form of intervals, e.g. ``[1, 5)``."""

import re

from .model import Interval

_NUM = r"-?\d+(?:\.\d+)?"
_PATTERN = re.compile(rf"^\s*\[\s*({_NUM})\s*,\s*({_NUM})\s*\)\s*$")


def _number(text):
    return float(text) if "." in text else int(text)


def parse(text):
    m = _PATTERN.match(text)
    if not m:
        raise ValueError(f"not an interval: {text!r}")
    return Interval(_number(m.group(1)), _number(m.group(2)))


def format_interval(interval):
    return str(interval)
