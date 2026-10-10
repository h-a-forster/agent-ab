"""Predicates over records and ways to combine them."""

import re

from . import levels


def min_level(minimum):
    """Keep records whose level is ``minimum`` or more severe (DEBUG < INFO < WARN < ERROR < FATAL)."""
    wanted = levels.parse_level(minimum)
    return lambda record: record.level >= wanted


def field_equals(name, value):
    return lambda record: record.get(name) == value


def field_matches(name, pattern, flags=0):
    regex = re.compile(pattern, flags)
    return lambda record: record.get(name) is not None and regex.search(str(record.get(name))) is not None


def has_field(name):
    return lambda record: record.get(name) is not None


def message_contains(text, case_sensitive=False):
    needle = text if case_sensitive else text.lower()

    def check(record):
        haystack = record.msg if case_sensitive else record.msg.lower()
        return needle in haystack

    return check


def between(start, end):
    """Records with ``start <= ts < end``."""
    return lambda record: start <= record.ts < end


def all_of(*predicates):
    return lambda record: all(p(record) for p in predicates)


def any_of(*predicates):
    return lambda record: any(p(record) for p in predicates)


def negate(predicate):
    return lambda record: not predicate(record)
