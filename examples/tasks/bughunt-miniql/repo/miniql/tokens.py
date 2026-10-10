"""Tokenizer for the miniql dialect."""

from .errors import ParseError

KEYWORDS = {
    "SELECT", "DISTINCT", "FROM", "WHERE", "GROUP", "BY", "HAVING", "ORDER", "ASC", "DESC",
    "LIMIT", "OFFSET", "AS", "AND", "OR", "NOT", "NULL", "TRUE", "FALSE", "IS", "IN", "LIKE",
    "BETWEEN", "CASE", "WHEN", "THEN", "ELSE", "END",
}

TWO_CHAR_OPS = ("<=", ">=", "<>", "!=")
ONE_CHAR_OPS = "=<>+-*/%(),"


class Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return "Token(%s, %r)" % (self.kind, self.value)


def tokenize(text):
    """Turn query text into a list of tokens ending with an ``EOF`` token.

    Kinds: NUMBER, STRING, IDENT, KEYWORD, OP, EOF.  Keywords are case-insensitive and
    normalised to upper case; identifiers keep their case.  Strings use single quotes and
    ``''`` for an embedded quote.
    """
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "'":
            start = i
            i += 1
            parts = []
            while True:
                if i >= n:
                    raise ParseError("unterminated string", start)
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        parts.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                parts.append(text[i])
                i += 1
            tokens.append(Token("STRING", "".join(parts), start))
        elif ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            start = i
            seen_dot = False
            while i < n and (text[i].isdigit() or (text[i] == "." and not seen_dot)):
                if text[i] == ".":
                    seen_dot = True
                i += 1
            raw = text[start:i]
            tokens.append(Token("NUMBER", float(raw) if seen_dot else int(raw), start))
        elif ch.isalpha() or ch == "_":
            start = i
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
            word = text[start:i]
            if word.upper() in KEYWORDS:
                tokens.append(Token("KEYWORD", word.upper(), start))
            else:
                tokens.append(Token("IDENT", word, start))
        elif text[i:i + 2] in TWO_CHAR_OPS:
            tokens.append(Token("OP", "<>" if text[i:i + 2] == "!=" else text[i:i + 2], i))
            i += 2
        elif ch in ONE_CHAR_OPS:
            tokens.append(Token("OP", ch, i))
            i += 1
        else:
            raise ParseError("unexpected character %r" % ch, i)
    tokens.append(Token("EOF", None, n))
    return tokens
