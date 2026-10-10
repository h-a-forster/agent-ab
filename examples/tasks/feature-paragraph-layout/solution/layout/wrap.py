"""Line breaking. A word is a maximal run of non-whitespace; its width is len(word)."""


def wrap(words, width):
    """Greedy fill: put as many words on a line as fit in `width` columns.

    A word wider than `width` gets a line of its own. Returns a list of lists of words.
    """
    lines = []
    cur = []
    cur_len = 0
    for w in words:
        extra = len(w) if not cur else cur_len + 1 + len(w)
        if cur and extra > width:
            lines.append(cur)
            cur, cur_len = [w], len(w)
        else:
            cur.append(w)
            cur_len = extra
    if cur:
        lines.append(cur)
    return lines
