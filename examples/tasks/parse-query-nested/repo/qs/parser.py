"""Parse query strings."""

from __future__ import annotations

from .codec import unquote_plus
from .tree import assign


def parse(query: str) -> dict:
    """Parse ``a=1&b=2`` into ``{"a": "1", "b": "2"}``; repeated keys become lists."""
    if query.startswith("?"):
        query = query[1:]
    tree: dict = {}
    for pair in query.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        key = unquote_plus(key)
        if not key:
            continue
        assign(tree, [key], unquote_plus(value))
    return tree
