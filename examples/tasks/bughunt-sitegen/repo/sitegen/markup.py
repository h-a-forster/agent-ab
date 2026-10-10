"""A very small markdown subset for page bodies."""

import re

from .util import escape_html

_INLINE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"), r"<em>\1</em>"),
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r'<a href="\2">\1</a>'),
]
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")


def inline(text):
    out = escape_html(text).replace("&quot;", '"')
    for pattern, replacement in _INLINE:
        out = pattern.sub(replacement, out)
    return out


def render_markdown(text):
    """Headings (``#``), unordered lists (``- ``) and paragraphs; inline bold / em / code / links."""
    blocks = [b for b in re.split(r"\n\s*\n", text.strip("\n")) if b.strip()]
    html = []
    for block in blocks:
        lines = block.split("\n")
        m = _HEADING.match(lines[0])
        if m and len(lines) == 1:
            level = len(m.group(1))
            html.append("<h%d>%s</h%d>" % (level, inline(m.group(2)), level))
        elif all(line.startswith("- ") for line in lines):
            items = "".join("<li>%s</li>" % inline(line[2:]) for line in lines)
            html.append("<ul>%s</ul>" % items)
        else:
            html.append("<p>%s</p>" % inline(" ".join(line.strip() for line in lines)))
    return "\n".join(html)
