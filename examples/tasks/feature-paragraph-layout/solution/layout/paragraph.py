"""Formatting whole paragraphs and texts."""
import re

from .align import align_pieces
from .optimal import break_optimal, split_words
from .wrap import wrap

_BLANK = re.compile(r"\n[ \t\r\f\v]*\n")


def format_paragraph(text, width, align="left", indent=0, first_indent=None, method="greedy"):
    """Break `text` into lines of at most `width` columns (indentation included).

    Returns a list of lines; an empty or all-blank text gives []. `indent` spaces start every
    line except the first, which starts with `first_indent` (default: `indent`). Words wider
    than the available space overflow on a line of their own.
    `method`: "greedy" (fill each line) or "optimal" (minimum total badness, see optimal.py).
    """
    if first_indent is None:
        first_indent = indent
    if width < 1 or not (0 <= indent < width) or not (0 <= first_indent < width):
        raise ValueError("bad width/indent")
    if method not in ("greedy", "optimal"):
        raise ValueError("unknown method %r" % (method,))
    avail_first, avail_rest = width - first_indent, width - indent
    if method == "greedy":
        words = text.split()
        pieces = words
        spaces = [True] * len(words)
        # the first line may have a different width, so fill it separately
        ranges = []
        i = 0
        n = len(words)
        while i < n:
            avail = avail_first if i == 0 else avail_rest
            j = i + 1
            length = len(words[i])
            while j < n and length + 1 + len(words[j]) <= avail:
                length += 1 + len(words[j])
                j += 1
            ranges.append((i, j))
            i = j
    else:
        pieces, spaces = split_words(text)
        ranges = break_optimal([len(p) for p in pieces], spaces, avail_first, avail_rest)
    out = []
    for n, (a, b) in enumerate(ranges):
        avail = avail_first if n == 0 else avail_rest
        pad = first_indent if n == 0 else indent
        line = align_pieces(pieces[a:b], [True] + list(spaces[a + 1:b]), avail, align, last=n == len(ranges) - 1)
        out.append(" " * pad + line)
    return out


def format_text(text, width, **kwargs):
    """Format every paragraph (separated by blank lines); paragraphs are joined by one empty line."""
    blocks = []
    for para in _BLANK.split(text):
        lines = format_paragraph(para, width, **kwargs)
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
