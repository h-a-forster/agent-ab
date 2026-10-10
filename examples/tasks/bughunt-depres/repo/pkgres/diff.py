"""Compare two resolutions (for example an old and a new lockfile)."""


class Change:
    """One package that differs between two resolutions."""

    def __init__(self, name, old, new):
        self.name = name
        self.old = old
        self.new = new

    @property
    def kind(self):
        if self.old is None:
            return "added"
        if self.new is None:
            return "removed"
        return "upgraded" if self.new > self.old else "downgraded"

    def __repr__(self):
        return "Change(%s: %s -> %s)" % (self.name, self.old, self.new)

    def __eq__(self, other):
        return isinstance(other, Change) and (self.name, self.old, self.new) == (other.name, other.old, other.new)

    def __hash__(self):
        return hash((self.name, self.old, self.new))


def diff(old, new):
    """Changes between two resolutions, sorted by package name; unchanged packages are omitted."""
    changes = []
    for name in sorted(set(old.names()) | set(new.names())):
        before = old[name] if name in old else None
        after = new[name] if name in new else None
        if before is None or after is None or not before.identical(after):
            changes.append(Change(name, before, after))
    return changes


def summarize(changes):
    """``{"added": n, "removed": n, "upgraded": n, "downgraded": n}`` (zero counts included)."""
    counts = {"added": 0, "removed": 0, "upgraded": 0, "downgraded": 0}
    for change in changes:
        counts[change.kind] += 1
    return counts


def format_changes(changes):
    marks = {"added": "+", "removed": "-", "upgraded": "^", "downgraded": "v"}
    lines = []
    for c in changes:
        if c.kind == "added":
            lines.append("%s %s %s" % (marks[c.kind], c.name, c.new))
        elif c.kind == "removed":
            lines.append("%s %s %s" % (marks[c.kind], c.name, c.old))
        else:
            lines.append("%s %s %s -> %s" % (marks[c.kind], c.name, c.old, c.new))
    return "\n".join(lines)
