"""Formula tokenizer."""

from .errors import FormulaSyntaxError
from .refs import is_ref

TWO = ("<>", "<=", ">=")
ONE = "+-*/^&=<>(),:"


class Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos

    def __repr__(self):
        return "Token(%s, %r)" % (self.kind, self.value)


def tokenize(text):
    """Kinds: NUM, STR, REF, FUNC (name directly followed by ``(``), NAME, OP, EOF."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            start = i
            seen_dot = False
            while i < n and (text[i].isdigit() or (text[i] == "." and not seen_dot)):
                seen_dot = seen_dot or text[i] == "."
                i += 1
            if i < n and text[i] in "eE" and i + 1 < n and (text[i + 1].isdigit() or text[i + 1] in "+-"):
                j = i + 2
                while j < n and text[j].isdigit():
                    j += 1
                i = j
            raw = text[start:i]
            tokens.append(Token("NUM", float(raw) if any(c in raw for c in ".eE") else int(raw), start))
        elif ch == '"':
            start = i
            i += 1
            parts = []
            while True:
                if i >= n:
                    raise FormulaSyntaxError("unterminated string", start)
                if text[i] == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        parts.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                parts.append(text[i])
                i += 1
            tokens.append(Token("STR", "".join(parts), start))
        elif text.startswith("#REF!", i):
            tokens.append(Token("NAME", "#REF!", i))
            i += 5
        elif ch.isalpha() or ch in "_$":
            start = i
            while i < n and (text[i].isalnum() or text[i] in "_$."):
                i += 1
            word = text[start:i]
            rest = text[i:].lstrip()
            if rest.startswith("("):
                tokens.append(Token("FUNC", word.upper(), start))
            elif is_ref(word):
                tokens.append(Token("REF", word, start))
            else:
                tokens.append(Token("NAME", word.upper(), start))
        elif text[i:i + 2] in TWO:
            tokens.append(Token("OP", text[i:i + 2], i))
            i += 2
        elif ch in ONE:
            tokens.append(Token("OP", ch, i))
            i += 1
        else:
            raise FormulaSyntaxError("unexpected character %r" % ch, i)
    tokens.append(Token("EOF", None, n))
    return tokens
