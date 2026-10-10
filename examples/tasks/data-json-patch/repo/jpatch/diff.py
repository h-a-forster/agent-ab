"""Generate a patch that turns one document into another."""

from __future__ import annotations

from .equality import json_equal


def diff(a, b) -> list[dict]:
    """Operations that turn ``a`` into ``b``."""
    ops: list[dict] = []
    _diff(a, b, "", ops)
    return ops


def _diff(a, b, path: str, ops: list[dict]) -> None:
    if a == b:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in a:
            if key not in b:
                ops.append({"op": "remove", "path": f"{path}/{key}"})
        for key in b:
            if key not in a:
                ops.append({"op": "add", "path": f"{path}/{key}", "value": b[key]})
            else:
                _diff(a[key], b[key], f"{path}/{key}", ops)
        return
    ops.append({"op": "replace", "path": path, "value": b})
