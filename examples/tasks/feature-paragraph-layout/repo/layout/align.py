"""Placing the words of one line inside `width` columns."""


def justify_words(words, width):
    """Stretch the gaps so the line is exactly `width` wide (if it has at least two words).

    Every gap gets at least one space; the extra spaces are shared evenly and the leftover
    ones go to the leftmost gaps. A line that is already too wide is returned unchanged.
    """
    text = " ".join(words)
    gaps = len(words) - 1
    extra = width - len(text)
    if gaps < 1 or extra <= 0:
        return text
    base, rem = divmod(extra, gaps)
    out = []
    for i, w in enumerate(words):
        out.append(w)
        if i < gaps:
            out.append(" " * (1 + base + (1 if i < rem else 0)))
    return "".join(out)


def align_line(words, width, align, last=False):
    """Format one line (no indentation). `align`: left, right, center or justify.

    The last line of a paragraph is never justified (it is left-aligned).
    """
    text = " ".join(words)
    if align == "justify":
        return text if last else justify_words(words, width)
    pad = max(0, width - len(text))
    if align == "right":
        return " " * pad + text
    if align == "center":
        return " " * (pad // 2) + text
    if align == "left":
        return text
    raise ValueError("unknown alignment %r" % (align,))
