"""Percent-encoding helpers."""

from __future__ import annotations

import re

_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PERCENT_RUN = re.compile(r"(?:%[0-9A-Fa-f]{2})+")


def unquote_plus(text: str) -> str:
    """Turn ``+`` into a space and decode ``%XX`` escapes as UTF-8 (invalid bytes -> U+FFFD)."""
    text = text.replace("+", " ")
    return _PERCENT_RUN.sub(
        lambda m: bytes.fromhex(m.group().replace("%", "")).decode("utf-8", "replace"), text
    )


def quote(text: str) -> str:
    """Percent-encode the UTF-8 bytes of ``text`` except unreserved characters."""
    return "".join(
        chr(b) if b in _UNRESERVED else "%%%02X" % b for b in text.encode("utf-8")
    )
