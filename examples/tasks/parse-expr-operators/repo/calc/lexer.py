"""Tokeniser."""

from __future__ import annotations

import re
from typing import NamedTuple

from .errors import ParseError


class Token(NamedTuple):
    kind: str  # "num", "name", "op" or "end"
    text: str
    pos: int


_NUMBER = re.compile(r"\d+\.\d*|\.\d+|\d+")
_NAME = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
_OPS = ["+", "-", "*", "/", "(", ")", ","]


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        m = _NUMBER.match(text, i)
        if m:
            tokens.append(Token("num", m.group(), i))
            i = m.end()
            continue
        m = _NAME.match(text, i)
        if m:
            tokens.append(Token("name", m.group(), i))
            i = m.end()
            continue
        for op in _OPS:
            if text.startswith(op, i):
                tokens.append(Token("op", op, i))
                i += len(op)
                break
        else:
            raise ParseError(f"unexpected character {ch!r}", i)
    tokens.append(Token("end", "", len(text)))
    return tokens
