"""Percent-encoding helpers."""

from __future__ import annotations

import re

_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")


def unquote_plus(text: str) -> str:
    """Decode ``%XX`` escapes and turn ``+`` into a space."""
    text = _PERCENT.sub(lambda m: chr(int(m.group(1), 16)), text)
    return text.replace("+", " ")


def quote(text: str) -> str:
    """Percent-encode everything except unreserved characters."""
    out = []
    for ch in text:
        if ch in _UNRESERVED:
            out.append(ch)
        else:
            out.append("%%%02X" % ord(ch))
    return "".join(out)
