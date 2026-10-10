"""Parse query strings."""

from __future__ import annotations

import re

from .codec import unquote_plus
from .errors import ParseError
from .tree import assign

_STRUCTURED = re.compile(r"^([^\[\]]+)((?:\[[^\[\]]*\])*)$")
_GROUP = re.compile(r"\[([^\[\]]*)\]")


def parse(query: str, max_depth: int = 5) -> dict:
    """Parse a query string into a nested dict (see the README)."""
    if query.startswith("?"):
        query = query[1:]
    tree: dict = {}
    for pair in query.split("&"):
        if not pair:
            continue
        raw_key, _, raw_value = pair.partition("=")
        if not raw_key:
            continue
        value = unquote_plus(raw_value)
        match = _STRUCTURED.match(raw_key)
        if not match or not match.group(2):
            assign(tree, [unquote_plus(raw_key)], value)
            continue
        groups = _GROUP.findall(match.group(2))
        if len(groups) > max_depth:
            raise ParseError(f"nesting deeper than {max_depth} levels in {raw_key!r}")
        as_list = False
        if groups[-1] == "":
            as_list = True
            groups.pop()
        if "" in groups:
            raise ParseError("'[]' is only allowed at the end of a key")
        path = [unquote_plus(match.group(1))] + [unquote_plus(g) for g in groups]
        assign(tree, path, value, as_list)
    return tree
