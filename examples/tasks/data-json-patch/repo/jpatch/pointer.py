"""RFC 6901 JSON Pointers."""

from __future__ import annotations

from .errors import PointerError

_MISSING = object()


def escape_token(token: str) -> str:
    """Escape one reference token (``~`` -> ``~0``, ``/`` -> ``~1``)."""
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    return token.replace("~0", "~").replace("~1", "/")


def parse_pointer(pointer: str) -> list[str]:
    """Split a pointer into unescaped tokens. ``""`` is the whole document."""
    if not isinstance(pointer, str):
        raise PointerError("pointer must be a string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise PointerError(f"pointer must start with '/': {pointer!r}")
    return [_unescape(t) for t in pointer[1:].split("/")]


def resolve(doc, pointer: str, default=_MISSING):
    """Return the value ``pointer`` points at, or ``default`` (else raise ``PointerError``)."""
    value = doc
    for token in parse_pointer(pointer):
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        elif default is not _MISSING:
            return default
        else:
            raise PointerError(f"cannot resolve {pointer!r}")
    return value
