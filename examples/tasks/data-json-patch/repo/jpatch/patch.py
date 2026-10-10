"""RFC 6902 JSON Patch (add, remove and replace only so far)."""

from __future__ import annotations

from .errors import PatchError
from .pointer import parse_pointer


def apply_patch(doc, ops):
    """Apply the operations in ``ops`` to ``doc`` and return the result."""
    for index, op in enumerate(ops):
        name = op.get("op")
        tokens = parse_pointer(op["path"])
        if name == "add":
            doc = _add(doc, tokens, op["value"])
        elif name == "remove":
            doc = _remove(doc, tokens)
        elif name == "replace":
            doc = _replace(doc, tokens, op["value"])
        else:
            raise PatchError(index, f"unsupported op {name!r}")
    return doc


def _parent(doc, tokens):
    for token in tokens[:-1]:
        doc = doc[int(token)] if isinstance(doc, list) else doc[token]
    return doc


def _add(doc, tokens, value):
    if not tokens:
        return value
    parent = _parent(doc, tokens)
    key = tokens[-1]
    if isinstance(parent, list):
        parent.insert(int(key), value)
    else:
        parent[key] = value
    return doc


def _remove(doc, tokens):
    parent = _parent(doc, tokens)
    key = tokens[-1]
    if isinstance(parent, list):
        del parent[int(key)]
    else:
        del parent[key]
    return doc


def _replace(doc, tokens, value):
    if not tokens:
        return value
    parent = _parent(doc, tokens)
    key = tokens[-1]
    if isinstance(parent, list):
        parent[int(key)] = value
    else:
        parent[key] = value
    return doc
