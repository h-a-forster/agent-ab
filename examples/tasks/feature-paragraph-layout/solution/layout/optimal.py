"""Optimal line breaking (minimum total badness) over boxes.

A paragraph is a sequence of boxes (word pieces); `space_before[k]` says whether a space
separates box k-1 from box k (False: the piece continues the same word after a hyphen).
"""


def split_words(text):
    """-> (pieces, space_before). A word is split after every '-' that sits between two
    alphanumeric characters; the hyphen stays at the end of the piece."""
    pieces = []
    space_before = []
    for word in text.split():
        start = 0
        first = True
        for k in range(1, len(word) - 1):
            if word[k] == "-" and word[k - 1].isalnum() and word[k + 1].isalnum():
                pieces.append(word[start:k + 1])
                space_before.append(first)
                first = False
                start = k + 1
        pieces.append(word[start:])
        space_before.append(first)
    return pieces, space_before


def break_optimal(lens, space_before, avail_first, avail_rest):
    """Return the list of (start, end) box ranges (end exclusive) of the optimal layout.

    Cost of a line that is not the last: (available - natural length) ** 2; the last line, and a
    single box wider than the line, cost 0. Ties: the lexicographically largest sequence of
    line lengths (in boxes)."""
    n = len(lens)
    if n == 0:
        return []
    INF = float("inf")
    best = [INF] * (n + 1)
    nxt = [0] * n
    best[n] = 0
    for i in range(n - 1, -1, -1):
        avail = avail_first if i == 0 else avail_rest
        length = 0
        bj, bc = -1, INF
        for j in range(i, n):
            length += lens[j] + (1 if j > i and space_before[j] else 0)
            overfull = length > avail
            if overfull and j > i:
                break
            if j == n - 1 or overfull:
                cost = 0
            else:
                cost = (avail - length) ** 2
            total = cost + best[j + 1]
            if total <= bc:
                bc, bj = total, j
            if overfull:
                break
        best[i] = bc
        nxt[i] = bj + 1
    lines = []
    i = 0
    while i < n:
        lines.append((i, nxt[i]))
        i = nxt[i]
    return lines
