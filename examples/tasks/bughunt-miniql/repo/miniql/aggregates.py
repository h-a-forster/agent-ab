"""Aggregate functions over lists of values."""

from .errors import ExecError
from .values import sort_key


def _non_null(values):
    return [v for v in values if v is not None]


def count_star(rows):
    return len(rows)


def count(values, distinct=False):
    present = _non_null(values)
    return len(set(present)) if distinct else len(present)


def total(values, distinct=False):
    present = _non_null(values)
    if distinct:
        present = list(set(present))
    if not present:
        return None
    for v in present:
        if isinstance(v, (str, bool)):
            raise ExecError("SUM needs numbers")
    return sum(present)


def average(values, distinct=False):
    present = _non_null(values)
    if distinct:
        present = list(set(present))
    if not present:
        return None
    for v in present:
        if isinstance(v, (str, bool)):
            raise ExecError("AVG needs numbers")
    return sum(present) / len(present)


def minimum(values, distinct=False):
    present = _non_null(values)
    return min(present, key=sort_key) if present else None


def maximum(values, distinct=False):
    present = _non_null(values)
    return max(present, key=sort_key) if present else None


FUNCTIONS = {"COUNT": count, "SUM": total, "AVG": average, "MIN": minimum, "MAX": maximum}


def apply(name, values, distinct=False):
    return FUNCTIONS[name](values, distinct)
