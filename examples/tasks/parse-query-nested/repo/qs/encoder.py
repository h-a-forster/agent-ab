"""Encode flat dicts as query strings."""

from __future__ import annotations

from .codec import quote


def encode(data: dict) -> str:
    """Encode a flat ``{key: str | [str, ...]}`` dict, keeping key order."""
    pairs = []
    for key, value in data.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            pairs.append(f"{quote(key)}={quote(str(item))}")
    return "&".join(pairs)
