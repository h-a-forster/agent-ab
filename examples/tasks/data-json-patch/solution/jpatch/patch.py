"""RFC 6902 JSON Patch."""

from __future__ import annotations

import copy

from .equality import json_equal
from .errors import PatchError, PointerError
from .pointer import parse_index, parse_pointer, resolve

_NEEDS_VALUE = {"add", "replace", "test"}
_NEEDS_FROM = {"move", "copy"}
_OPS = {"add", "remove", "replace", "move", "copy", "test"}


def apply_patch(doc, ops):
    """Return a copy of ``doc`` with ``ops`` applied; ``doc`` and ``ops`` are never modified.

    Raises :class:`PatchError` (with the failing operation's index) and returns nothing if any
    operation fails.
    """
    if not isinstance(ops, list):
        raise PatchError(None, "a patch must be a list of operations")
    result = copy.deepcopy(doc)
    for index, op in enumerate(ops):
        try:
            result = _apply_one(result, op)
        except (PointerError, PatchError) as exc:
            message = exc.message if isinstance(exc, PatchError) else str(exc)
            raise PatchError(index, message) from None
    return result


def _apply_one(doc, op):
    if not isinstance(op, dict):
        raise PatchError(None, "operation must be an object")
    name = op.get("op")
    if name not in _OPS:
        raise PatchError(None, f"unsupported op {name!r}")
    if not isinstance(op.get("path"), str):
        raise PatchError(None, "missing or invalid 'path'")
    if name in _NEEDS_VALUE and "value" not in op:
        raise PatchError(None, f"{name} requires 'value'")
    if name in _NEEDS_FROM and not isinstance(op.get("from"), str):
        raise PatchError(None, f"{name} requires 'from'")
    tokens = parse_pointer(op["path"])
    if name == "add":
        return _add(doc, tokens, copy.deepcopy(op["value"]))
    if name == "remove":
        return _remove(doc, tokens)
    if name == "replace":
        return _replace(doc, tokens, copy.deepcopy(op["value"]))
    if name == "test":
        found = resolve(doc, op["path"])
        if not json_equal(found, op["value"]):
            raise PatchError(None, f"test failed at {op['path']!r}")
        return doc
    src = parse_pointer(op["from"])
    value = resolve(doc, op["from"])
    if name == "copy":
        return _add(doc, tokens, copy.deepcopy(value))
    if tokens[: len(src)] == src and len(tokens) > len(src):
        raise PatchError(None, "cannot move a value into itself")
    if tokens == src:
        return doc
    return _add(_remove(doc, src), tokens, value)


def _parent(doc, tokens):
    for token in tokens[:-1]:
        if isinstance(doc, dict) and token in doc:
            doc = doc[token]
        elif isinstance(doc, list):
            doc = doc[parse_index(token, len(doc))]
        else:
            raise PatchError(None, f"path does not exist: /{'/'.join(tokens)}")
    return doc


def _add(doc, tokens, value):
    if not tokens:
        return value
    parent = _parent(doc, tokens)
    key = tokens[-1]
    if isinstance(parent, list):
        if key == "-":
            parent.append(value)
        else:
            parent.insert(parse_index(key, len(parent), allow_end=True), value)
    elif isinstance(parent, dict):
        parent[key] = value
    else:
        raise PatchError(None, "cannot add into a scalar")
    return doc


def _remove(doc, tokens):
    if not tokens:
        raise PatchError(None, "cannot remove the document root")
    parent = _parent(doc, tokens)
    key = tokens[-1]
    if isinstance(parent, list):
        del parent[parse_index(key, len(parent))]
    elif isinstance(parent, dict) and key in parent:
        del parent[key]
    else:
        raise PatchError(None, f"path does not exist: /{'/'.join(tokens)}")
    return doc


def _replace(doc, tokens, value):
    if not tokens:
        return value
    parent = _parent(doc, tokens)
    key = tokens[-1]
    if isinstance(parent, list):
        parent[parse_index(key, len(parent))] = value
    elif isinstance(parent, dict) and key in parent:
        parent[key] = value
    else:
        raise PatchError(None, f"path does not exist: /{'/'.join(tokens)}")
    return doc
