"""Generate a patch that turns one document into another."""

from __future__ import annotations

import copy

from .equality import json_equal
from .pointer import escape_token


def diff(a, b) -> list[dict]:
    """Operations that turn ``a`` into ``b`` (values are deep copies)."""
    ops: list[dict] = []
    _diff(a, b, "", ops)
    return ops


def _diff(a, b, path: str, ops: list[dict]) -> None:
    if json_equal(a, b):
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a:
            if key not in b:
                ops.append({"op": "remove", "path": f"{path}/{escape_token(key)}"})
        for key in b:
            sub = f"{path}/{escape_token(key)}"
            if key not in a:
                ops.append({"op": "add", "path": sub, "value": copy.deepcopy(b[key])})
            else:
                _diff(a[key], b[key], sub, ops)
        return
    if isinstance(a, list) and isinstance(b, list):
        common = min(len(a), len(b))
        for i in range(common):
            _diff(a[i], b[i], f"{path}/{i}", ops)
        for i in range(common, len(b)):
            ops.append({"op": "add", "path": f"{path}/{i}", "value": copy.deepcopy(b[i])})
        for i in range(len(a) - 1, len(b) - 1, -1):
            ops.append({"op": "remove", "path": f"{path}/{i}"})
        return
    ops.append({"op": "replace", "path": path, "value": copy.deepcopy(b)})
