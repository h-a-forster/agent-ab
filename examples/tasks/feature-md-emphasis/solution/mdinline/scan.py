"""Splits inline Markdown into nodes.

Every node is ("text", str), ("code", str) or ("delim", char, length, can_open, can_close) for a
run of `*` or `_` (flanking is computed from the characters around the run in the source).
"""
from .chars import ASCII_PUNCTUATION, is_punctuation, is_whitespace


def _code_content(raw):
    s = raw.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    if len(s) >= 2 and s[0] == " " and s[-1] == " " and s.strip(" "):
        s = s[1:-1]
    return s


def _flanking(text, i, j, ch):
    before = text[i - 1] if i > 0 else " "
    after = text[j] if j < len(text) else " "
    ws_b, ws_a = is_whitespace(before), is_whitespace(after)
    p_b, p_a = is_punctuation(before), is_punctuation(after)
    left = not ws_a and (not p_a or ws_b or p_b)
    right = not ws_b and (not p_b or ws_a or p_a)
    if ch == "*":
        return left, right
    return left and (not right or p_b), right and (not left or p_a)


def scan(text):
    nodes = []
    buf = []

    def flush():
        if buf:
            nodes.append(("text", "".join(buf)))
            buf.clear()

    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n and text[i + 1] in ASCII_PUNCTUATION:
            buf.append(text[i + 1])
            i += 2
        elif c == "`":
            j = i
            while j < n and text[j] == "`":
                j += 1
            ticks = text[i:j]
            k = j
            end = -1
            while k < n:
                if text[k] == "`":
                    m = k
                    while m < n and text[m] == "`":
                        m += 1
                    if m - k == len(ticks):
                        end = k
                        break
                    k = m
                else:
                    k += 1
            if end < 0:
                buf.append(ticks)
                i = j
            else:
                flush()
                nodes.append(("code", _code_content(text[j:end])))
                i = end + len(ticks)
        elif c == "*" or c == "_":
            j = i
            while j < n and text[j] == c:
                j += 1
            flush()
            can_open, can_close = _flanking(text, i, j, c)
            nodes.append(("delim", c, j - i, can_open, can_close))
            i = j
        else:
            buf.append(c)
            i += 1
    flush()
    return nodes
