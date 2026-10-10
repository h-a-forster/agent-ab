"""Splits inline Markdown into nodes.

Supported: backslash escapes of ASCII punctuation, code spans, plain text. Every node is a tuple
("text", str) or ("code", str); everything else (including * and _) is plain text for now.
"""
from .chars import ASCII_PUNCTUATION


def _code_content(raw):
    s = raw.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    if len(s) >= 2 and s[0] == " " and s[-1] == " " and s.strip(" "):
        s = s[1:-1]
    return s


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
        else:
            buf.append(c)
            i += 1
    flush()
    return nodes
