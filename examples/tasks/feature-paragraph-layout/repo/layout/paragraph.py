"""Formatting whole paragraphs and texts."""
import re

from .align import align_line
from .wrap import wrap

_BLANK = re.compile(r"\n[ \t\r\f\v]*\n")


def format_paragraph(text, width, align="left", indent=0):
    """Greedy-wrap `text` into lines of at most `width` columns (indentation included).

    Returns a list of lines; an empty or all-blank text gives []. Words wider than the
    available space overflow on a line of their own. `indent` spaces start every line.
    """
    if width < 1 or indent < 0 or indent >= width:
        raise ValueError("bad width/indent")
    avail = width - indent
    words = text.split()
    out = []
    lines = wrap(words, avail)
    for n, line in enumerate(lines):
        out.append(" " * indent + align_line(line, avail, align, last=n == len(lines) - 1))
    return out


def format_text(text, width, **kwargs):
    """Format every paragraph (separated by blank lines); paragraphs are joined by one empty line."""
    blocks = []
    for para in _BLANK.split(text):
        lines = format_paragraph(para, width, **kwargs)
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
