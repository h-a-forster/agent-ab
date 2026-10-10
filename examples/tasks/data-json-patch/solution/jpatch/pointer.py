"""RFC 6901 JSON Pointers."""

from __future__ import annotations

from .errors import PointerError

_MISSING = object()


def escape_token(token: str) -> str:
    """Escape one reference token (``~`` -> ``~0``, ``/`` -> ``~1``)."""
    return token.replace("~", "~0").replace("/", "~1")


def _unescape(token: str) -> str:
    out = []
    i = 0
    while i < len(token):
        ch = token[i]
        if ch == "~":
            nxt = token[i + 1 : i + 2]
            if nxt == "0":
                out.append("~")
            elif nxt == "1":
                out.append("/")
            else:
                raise PointerError(f"invalid escape in token {token!r}")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_index(token: str, size: int, allow_end: bool = False) -> int:
    """Strict array index: ``0`` or digits without leading zeros, below ``size`` (or equal if
    ``allow_end``)."""
    if not (token == "0" or (token[:1] in "123456789" and token.isascii() and token.isdigit())):
        raise PointerError(f"invalid array index {token!r}")
    index = int(token)
    if index > size or (index == size and not allow_end):
        raise PointerError(f"array index {index} out of range")
    return index


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
        elif isinstance(value, list) and _valid_index(token, len(value)):
            value = value[int(token)]
        elif default is not _MISSING:
            return default
        else:
            raise PointerError(f"cannot resolve {pointer!r}")
    return value


def _valid_index(token: str, size: int) -> bool:
    try:
        parse_index(token, size)
    except PointerError:
        return False
    return True
