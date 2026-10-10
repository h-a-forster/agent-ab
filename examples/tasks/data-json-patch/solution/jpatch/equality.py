"""JSON value equality."""

from __future__ import annotations


def json_equal(a, b) -> bool:
    """True if ``a`` and ``b`` are equal JSON values (``true`` is not ``1``)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, dict):
        return (
            isinstance(b, dict)
            and a.keys() == b.keys()
            and all(json_equal(v, b[k]) for k, v in a.items())
        )
    if isinstance(a, (list, tuple)):
        return (
            isinstance(b, (list, tuple))
            and len(a) == len(b)
            and all(json_equal(x, y) for x, y in zip(a, b))
        )
    if isinstance(b, (dict, list, tuple)):
        return False
    return a == b
