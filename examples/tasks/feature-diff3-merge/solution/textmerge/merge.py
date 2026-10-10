"""Three-way merge at line level (diff3 style clustering of changes)."""
from .diff import hunks
from .lines import join_lines, split_lines


class MergeConflict(Exception):
    """The merge has conflicts. `result` holds the MergeResult (with conflict markers)."""

    def __init__(self, message="conflict", result=None):
        super().__init__(message)
        self.result = result


class MergeResult:
    def __init__(self, lines, conflicts):
        self.lines = lines
        self.conflicts = conflicts

    @property
    def text(self):
        return join_lines(self.lines)

    @property
    def clean(self):
        return self.conflicts == 0


def _apply(base, start, end, side_hunks, side):
    out = []
    pos = start
    for a0, a1, s0, s1 in side_hunks:
        out.extend(base[pos:a0])
        out.extend(side[s0:s1])
        pos = a1
    out.extend(base[pos:end])
    return out


def _terminated(lines):
    if lines and not lines[-1].endswith("\n"):
        return lines[:-1] + [lines[-1] + "\n"]
    return lines


def merge3(base, ours, theirs, labels=("ours", "base", "theirs"), style="merge"):
    if style not in ("merge", "diff3"):
        raise ValueError("unknown style %r" % (style,))
    tagged = [(h[0], h[1], 0, h) for h in hunks(base, ours)] + [(h[0], h[1], 1, h) for h in hunks(base, theirs)]
    tagged.sort(key=lambda t: (t[0], t[1], t[2]))
    clusters = []
    for start, end, side, h in tagged:
        if clusters and start <= clusters[-1][1]:
            c = clusters[-1]
            c[1] = max(c[1], end)
            c[2 + side].append(h)
        else:
            clusters.append([start, end, [h] if side == 0 else [], [h] if side == 1 else []])
    out = []
    conflicts = 0
    pos = 0
    for start, end, oh, th in clusters:
        out.extend(base[pos:start])
        pos = end
        b_text = base[start:end]
        o_text = _apply(base, start, end, oh, ours)
        t_text = _apply(base, start, end, th, theirs)
        if o_text == t_text or t_text == b_text:
            out.extend(o_text)
        elif o_text == b_text:
            out.extend(t_text)
        else:
            conflicts += 1
            k = 0
            while k < len(o_text) and k < len(t_text) and o_text[k] == t_text[k]:
                k += 1
            out.extend(o_text[:k])
            o_text, t_text = o_text[k:], t_text[k:]
            j = 0
            while j < len(o_text) and j < len(t_text) and o_text[-1 - j] == t_text[-1 - j]:
                j += 1
            tail = o_text[len(o_text) - j:]
            o_text, t_text = o_text[:len(o_text) - j], t_text[:len(t_text) - j]
            out.append("<<<<<<< %s\n" % labels[0])
            out.extend(_terminated(o_text))
            if style == "diff3":
                out.append("||||||| %s\n" % labels[1])
                out.extend(_terminated(b_text))
            out.append("=======\n")
            out.extend(_terminated(t_text))
            out.append(">>>>>>> %s\n" % labels[2])
            out.extend(tail)
    out.extend(base[pos:])
    return MergeResult(out, conflicts)


def merge_text(base, ours, theirs, on_conflict="raise", labels=("ours", "base", "theirs"), style="merge"):
    """Return the merged text. With conflicts: raise MergeConflict (default) or, with
    on_conflict="markers", return the text with conflict markers."""
    if on_conflict not in ("raise", "markers"):
        raise ValueError("on_conflict must be 'raise' or 'markers'")
    result = merge3(split_lines(base), split_lines(ours), split_lines(theirs), labels, style)
    if result.conflicts and on_conflict == "raise":
        raise MergeConflict("%d conflict(s)" % result.conflicts, result)
    return result.text
