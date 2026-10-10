"""Build the nested result of a parse."""

from __future__ import annotations

from .errors import ParseError


def assign(tree: dict, path: list[str], value: str, as_list: bool = False) -> None:
    """Store ``value`` under ``path`` in ``tree``.

    Intermediate keys must be (or become) dicts. At the last key, a repeated key turns the
    value into a list; ``as_list`` forces a list even for the first value. Mixing dict and
    non-dict values under one key raises :class:`ParseError`.
    """
    node = tree
    for key in path[:-1]:
        child = node.get(key)
        if child is None:
            child = node[key] = {}
        elif not isinstance(child, dict):
            raise ParseError(f"key conflict at {key!r}")
        node = child
    last = path[-1]
    if last not in node:
        node[last] = [value] if as_list else value
        return
    existing = node[last]
    if isinstance(existing, dict):
        raise ParseError(f"key conflict at {last!r}")
    if isinstance(existing, list):
        existing.append(value)
    else:
        node[last] = [existing, value]
