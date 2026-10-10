"""SQL value semantics: three-valued logic, comparison, ordering and LIKE."""

import re

from .errors import ExecError


def tv_not(value):
    return None if value is None else not value


def tv_and(left, right):
    """Kleene AND: False wins over unknown."""
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


def tv_or(left, right):
    """Kleene OR: True wins over unknown."""
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


def _kind(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "text"
    return "other"


def compare(op, left, right):
    """Compare two values; any NULL operand gives NULL (None)."""
    if left is None or right is None:
        return None
    if _kind(left) != _kind(right):
        raise ExecError("cannot compare %s with %s" % (_kind(left), _kind(right)))
    if op == "=":
        return left == right
    if op == "<>":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    raise ExecError("unknown comparison %s" % op)


def in_list(value, items):
    """SQL ``value IN (items)``: True on a match, NULL if unmatched but NULLs are involved."""
    if value is None:
        return None
    saw_null = False
    for item in items:
        result = compare("=", value, item)
        if result is True:
            return True
        if result is None:
            saw_null = True
    return None if saw_null else False


def sort_key(value):
    """Ordering key: NULL sorts before every other value, numbers before text."""
    if value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (2, value)
    return (3, value)


_like_cache = {}


def like_regex(pattern):
    """Compile a LIKE pattern: ``%`` any run of characters, ``_`` exactly one, rest literal."""
    compiled = _like_cache.get(pattern)
    if compiled is None:
        out = []
        for ch in pattern:
            if ch == "%":
                out.append(".*")
            elif ch == "_":
                out.append(".")
            else:
                out.append(re.escape(ch))
        compiled = re.compile("".join(out), re.DOTALL)
        _like_cache[pattern] = compiled
    return compiled


def like(value, pattern):
    if value is None or pattern is None:
        return None
    if not isinstance(value, str) or not isinstance(pattern, str):
        raise ExecError("LIKE needs text operands")
    return like_regex(pattern).fullmatch(value) is not None


def arithmetic(op, left, right):
    if left is None or right is None:
        return None
    if _kind(left) != "number" or _kind(right) != "number":
        if op == "+" and _kind(left) == "text" and _kind(right) == "text":
            return left + right
        raise ExecError("operator %s needs numbers" % op)
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if right == 0:
        return None
    if op == "/":
        if isinstance(left, int) and isinstance(right, int):
            return left / right if left % right else left // right
        return left / right
    if op == "%":
        return left % right
    raise ExecError("unknown operator %s" % op)
