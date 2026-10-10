"""Just enough block structure for a README renderer: paragraphs and ATX headings."""
import re

from .render import plain_text, render_inline

_HEADING = re.compile(r"(#{1,6}) +(.*?)\s*$")


def _blocks(md):
    """Yield ("h", level, text) or ("p", text) blocks."""
    para = []
    for raw in md.split("\n"):
        line = raw.strip(" \t\r")
        m = _HEADING.fullmatch(line)
        if m:
            if para:
                yield ("p", "\n".join(para))
                para = []
            yield ("h", len(m.group(1)), m.group(2))
        elif not line:
            if para:
                yield ("p", "\n".join(para))
                para = []
        else:
            para.append(line)
    if para:
        yield ("p", "\n".join(para))


def render_document(md):
    out = []
    for block in _blocks(md):
        if block[0] == "h":
            out.append("<h%d>%s</h%d>" % (block[1], render_inline(block[2]), block[1]))
        else:
            out.append("<p>%s</p>" % render_inline(block[1]))
    return "\n".join(out)


def outline(md):
    """[(level, plain-text title)] of the headings, for a table of contents."""
    return [(b[1], plain_text(b[2])) for b in _blocks(md) if b[0] == "h"]
