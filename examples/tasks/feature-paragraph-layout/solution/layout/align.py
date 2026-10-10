"""Placing the pieces of one line inside `width` columns."""


def _stretch(pieces, spaces, width):
    """spaces[k] (k >= 1): True if a space (stretchable) sits between pieces k-1 and k."""
    gaps = [k for k in range(1, len(pieces)) if spaces[k]]
    text_len = sum(len(p) for p in pieces) + len(gaps)
    extra = width - text_len
    base, rem = (divmod(extra, len(gaps)) if gaps and extra > 0 else (0, 0))
    out = [pieces[0]]
    seen = 0
    for k in range(1, len(pieces)):
        if spaces[k]:
            out.append(" " * (1 + base + (1 if seen < rem else 0)))
            seen += 1
        out.append(pieces[k])
    return "".join(out)


def plain(pieces, spaces):
    out = [pieces[0]]
    for k in range(1, len(pieces)):
        if spaces[k]:
            out.append(" ")
        out.append(pieces[k])
    return "".join(out)


def justify_words(words, width):
    """Stretch the gaps so the line is exactly `width` wide (if it has at least two words).

    Every gap gets at least one space; the extra spaces are shared evenly and the leftover
    ones go to the leftmost gaps. A line that is already too wide is returned unchanged.
    """
    return _stretch(words, [True] * len(words), width)


def align_pieces(pieces, spaces, width, align, last=False):
    text = plain(pieces, spaces)
    if align == "justify":
        return text if last else _stretch(pieces, spaces, width)
    pad = max(0, width - len(text))
    if align == "right":
        return " " * pad + text
    if align == "center":
        return " " * (pad // 2) + text
    if align == "left":
        return text
    raise ValueError("unknown alignment %r" % (align,))


def align_line(words, width, align, last=False):
    """Format one line (no indentation). `align`: left, right, center or justify.

    The last line of a paragraph is never justified (it is left-aligned).
    """
    return align_pieces(words, [True] * len(words), width, align, last)
