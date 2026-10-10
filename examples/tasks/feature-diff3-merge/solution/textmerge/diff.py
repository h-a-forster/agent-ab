"""Line diff. A diff is a list of (op, line) with op one of "=", "-", "+".

Applying it: "=" and "-" consume a line of `a` (which must equal `line`), "=" and "+" produce
a line of `b`.

`diff` is Myers' O(ND) algorithm (greedy forward search with a trace for the backtrack);
common prefix and suffix are trimmed first.
"""


def _myers(a, b):
    """Shortest edit script for a -> b as a list of ("-", index in a) / ("+", index in b)."""
    n, m = len(a), len(b)
    if n == 0:
        return [("+", j) for j in range(m)]
    if m == 0:
        return [("-", i) for i in range(n)]
    off = n + m + 2
    v = [0] * (2 * off + 1)
    trace = []
    found = None
    for d in range(n + m + 1):
        trace.append(v[off - d - 1: off + d + 2])  # state after round d - 1; k is at k + d + 1
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v[off + k - 1] < v[off + k + 1]):
                x = v[off + k + 1]
            else:
                x = v[off + k - 1] + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[off + k] = x
            if x >= n and y >= m:
                found = d
                break
        if found is not None:
            break
    ops = []
    x, y = n, m
    for d in range(found, 0, -1):
        prev = trace[d]
        k = x - y
        if k == -d or (k != d and prev[k - 1 + d + 1] < prev[k + 1 + d + 1]):
            pk = k + 1
            px = prev[pk + d + 1]
            py = px - pk
            ops.append(("+", py))
        else:
            pk = k - 1
            px = prev[pk + d + 1]
            py = px - pk
            ops.append(("-", px))
        x, y = px, py
    ops.reverse()
    return ops


def diff(a, b):
    """Minimal line diff (fewest "-" plus "+" operations)."""
    n, m = len(a), len(b)
    lo = 0
    while lo < n and lo < m and a[lo] == b[lo]:
        lo += 1
    hi = 0
    while hi < n - lo and hi < m - lo and a[n - 1 - hi] == b[m - 1 - hi]:
        hi += 1
    out = [("=", x) for x in a[:lo]]
    i = j = 0
    ma, mb = a[lo:n - hi], b[lo:m - hi]
    for op, idx in _myers(ma, mb):
        if op == "-":
            while i < idx:
                out.append(("=", ma[i]))
                i += 1
                j += 1
            out.append(("-", ma[i]))
            i += 1
        else:
            while j < idx:
                out.append(("=", mb[j]))
                i += 1
                j += 1
            out.append(("+", mb[j]))
            j += 1
    while i < len(ma):
        out.append(("=", ma[i]))
        i += 1
    out.extend(("=", x) for x in a[n - hi:])
    return out


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


def hunks(a, b):
    """Changed regions as (a0, a1, b0, b1): a[a0:a1] was replaced by b[b0:b1]."""
    out = []
    i = j = 0
    cur = None
    for op, _ in diff(a, b):
        if op == "=":
            if cur:
                out.append((cur[0], i, cur[1], j))
                cur = None
            i += 1
            j += 1
            continue
        if cur is None:
            cur = (i, j)
        if op == "-":
            i += 1
        else:
            j += 1
    if cur:
        out.append((cur[0], i, cur[1], j))
    return out
