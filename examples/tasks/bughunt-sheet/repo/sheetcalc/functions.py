"""Spreadsheet functions that take already evaluated arguments."""

import math
from decimal import ROUND_HALF_UP, Decimal

from .errors import DIV0, NAME, NUM, VALUE, CellError, ErrorSignal


class RangeValue:
    """The values of a range, row by row."""

    def __init__(self, values, rows, cols):
        self.values = list(values)
        self.rows = rows
        self.cols = cols

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def to_number(v):
    """Coerce a scalar for arithmetic: empty -> 0, TRUE -> 1, numeric text -> number."""
    if isinstance(v, CellError):
        raise ErrorSignal(v)
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if is_number(v):
        return v
    if isinstance(v, str):
        try:
            return int(v) if v.strip().lstrip("+-").isdigit() else float(v)
        except ValueError:
            raise ErrorSignal(VALUE) from None
    raise ErrorSignal(VALUE)


def to_text(v):
    from .format import format_value

    if isinstance(v, CellError):
        raise ErrorSignal(v)
    return "" if v is None else format_value(v)


def to_bool(v):
    if isinstance(v, CellError):
        raise ErrorSignal(v)
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if is_number(v):
        return v != 0
    if isinstance(v, str) and v.upper() in ("TRUE", "FALSE"):
        return v.upper() == "TRUE"
    raise ErrorSignal(VALUE)


def flatten(args):
    for arg in args:
        if isinstance(arg, RangeValue):
            yield from arg.values
        else:
            yield arg


def numbers(args):
    """Numbers among the arguments (text, booleans and empty cells are skipped); errors propagate."""
    out = []
    for v in flatten(args):
        if isinstance(v, CellError):
            raise ErrorSignal(v)
        if is_number(v):
            out.append(v)
    return out


def round_half_away(value, digits=0):
    """Round to ``digits`` decimal places, halves away from zero (``-2.5`` -> ``-3``)."""
    if int(digits) <= 0:
        return int(round(value, int(digits)))
    return round(value, int(digits))


def _arity(args, low, high=None):
    high = low if high is None else high
    if not low <= len(args) <= high:
        raise ErrorSignal(VALUE)


def f_sum(args):
    return sum(numbers(args))


def f_average(args):
    nums = numbers(args)
    if not nums:
        raise ErrorSignal(DIV0)
    return sum(nums) / len(nums)


def f_min(args):
    nums = numbers(args)
    return min(nums) if nums else 0


def f_max(args):
    nums = numbers(args)
    return max(nums) if nums else 0


def f_count(args):
    return sum(1 for v in flatten(args) if is_number(v))


def f_counta(args):
    return sum(1 for v in flatten(args) if v is not None)


def f_round(args):
    _arity(args, 1, 2)
    value = to_number(args[0])
    digits = to_number(args[1]) if len(args) == 2 else 0
    return round_half_away(value, digits)


def f_abs(args):
    _arity(args, 1)
    return abs(to_number(args[0]))


def f_mod(args):
    _arity(args, 2)
    a, b = to_number(args[0]), to_number(args[1])
    if b == 0:
        raise ErrorSignal(DIV0)
    return a % b


def f_power(args):
    _arity(args, 2)
    return power(to_number(args[0]), to_number(args[1]))


def power(base, exponent):
    try:
        result = base ** exponent
    except ZeroDivisionError:
        raise ErrorSignal(DIV0) from None
    except OverflowError:
        raise ErrorSignal(NUM) from None
    if isinstance(result, complex):
        raise ErrorSignal(NUM)
    return result


def f_sqrt(args):
    _arity(args, 1)
    value = to_number(args[0])
    if value < 0:
        raise ErrorSignal(NUM)
    root = math.sqrt(value)
    return int(root) if root == int(root) else root


def f_and(args):
    return all(to_bool(v) for v in flatten(args) if v is not None)


def f_or(args):
    return any(to_bool(v) for v in flatten(args) if v is not None)


def f_not(args):
    _arity(args, 1)
    return not to_bool(args[0])


def f_concat(args):
    return "".join(to_text(v) for v in flatten(args))


def f_len(args):
    _arity(args, 1)
    return len(to_text(args[0]))


def f_upper(args):
    _arity(args, 1)
    return to_text(args[0]).upper()


def f_lower(args):
    _arity(args, 1)
    return to_text(args[0]).lower()


FUNCTIONS = {
    "SUM": f_sum, "AVERAGE": f_average, "MIN": f_min, "MAX": f_max, "COUNT": f_count, "COUNTA": f_counta,
    "ROUND": f_round, "ABS": f_abs, "MOD": f_mod, "POWER": f_power, "SQRT": f_sqrt,
    "AND": f_and, "OR": f_or, "NOT": f_not, "CONCAT": f_concat, "LEN": f_len, "UPPER": f_upper, "LOWER": f_lower,
}


def call(name, args):
    func = FUNCTIONS.get(name)
    if func is None:
        raise ErrorSignal(NAME)
    return func(args)
