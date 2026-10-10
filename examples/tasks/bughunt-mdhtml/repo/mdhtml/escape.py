"""HTML escaping helpers."""

import re

# An ampersand that already starts a character reference is left alone.
_ENTITY = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")


def escape_text(text):
    """Escape text for use between tags: ``& < >`` (existing entities are kept)."""
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "&":
            m = _ENTITY.match(text, i)
            if m:
                out.append(m.group(0))
                i = m.end()
                continue
            out.append("&amp;")
        elif ch == "<":
            out.append("&lt;")
        elif ch == ">":
            out.append("&gt;")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def escape_attr(text):
    """Escape text for use inside a double-quoted attribute value."""
    return escape_text(text).replace('"', "&quot;")


def escape_code(text):
    """Escape the content of code spans and blocks: every ``&`` is literal there."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
