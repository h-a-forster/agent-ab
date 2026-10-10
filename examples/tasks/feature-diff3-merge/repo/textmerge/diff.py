"""Line diff. A diff is a list of (op, line) with op one of "=", "-", "+".

Applying it: "=" and "-" consume a line of `a` (which must equal `line`), "=" and "+" produce
a line of `b`.
"""


def diff(a, b):
    """Longest-common-subsequence diff using the classic full table (O(len(a) * len(b)))."""
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a[i] == b[j]:
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])
    ops = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            ops.append(("=", a[i]))
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            ops.append(("-", a[i]))
            i += 1
        else:
            ops.append(("+", b[j]))
            j += 1
    ops.extend(("-", x) for x in a[i:])
    ops.extend(("+", x) for x in b[j:])
    return ops


def apply_diff(a, ops):
    """Rebuild `b` from `a` and a diff; raises ValueError if the diff does not fit `a`."""
    out = []
    i = 0
    for op, line in ops:
        if op in "=-":
            if i >= len(a) or a[i] != line:
                raise ValueError("diff does not apply at line %d" % i)
            i += 1
        if op in "=+":
            out.append(line)
    if i != len(a):
        raise ValueError("diff does not consume the whole input")
    return out
