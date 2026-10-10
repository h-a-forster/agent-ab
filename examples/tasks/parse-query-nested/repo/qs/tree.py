"""Build the nested result of a parse."""

from __future__ import annotations

from .errors import ParseError


def assign(tree: dict, path: list[str], value: str) -> None:
    """Store ``value`` under ``path`` (a flat list of keys) in ``tree``.

    A repeated key turns into a list of values.
    """
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
    last = path[-1]
    if last in node:
        existing = node[last]
        if isinstance(existing, list):
            existing.append(value)
        else:
            node[last] = [existing, value]
    else:
        node[last] = value
