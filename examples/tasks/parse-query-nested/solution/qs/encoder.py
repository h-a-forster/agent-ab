"""Encode nested dicts as query strings."""

from __future__ import annotations

from .codec import quote


def encode(data: dict) -> str:
    """Encode a nested dict (see the README); the inverse of :func:`qs.parse`."""
    if not isinstance(data, dict):
        raise TypeError("encode() needs a dict")
    pairs: list[str] = []
    _walk(data, [], pairs)
    return "&".join(pairs)


def _scalar(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise TypeError(f"cannot encode {type(value).__name__}")


def _key(path: list[str]) -> str:
    return quote(path[0]) + "".join(f"[{quote(seg)}]" for seg in path[1:])


def _walk(node: dict, path: list[str], pairs: list[str]) -> None:
    for key, value in node.items():
        if not isinstance(key, str):
            raise TypeError("keys must be strings")
        if key == "":
            raise ValueError("empty keys cannot be encoded")
        here = path + [key]
        if isinstance(value, dict):
            _walk(value, here, pairs)
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, (dict, list, tuple)):
                    raise ValueError("lists may only contain scalars")
                pairs.append(f"{_key(here)}[]={quote(_scalar(item))}")
        else:
            pairs.append(f"{_key(here)}={quote(_scalar(value))}")
