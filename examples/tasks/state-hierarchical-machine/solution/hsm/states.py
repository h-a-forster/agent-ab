"""Declared states, organised as a tree by dotted names."""


class StateSet:
    def __init__(self, names, initials=None):
        names = list(names)
        if len(set(names)) != len(names):
            raise ValueError("duplicate state names")
        if not names:
            raise ValueError("at least one state is required")
        self.names = tuple(names)
        known = set(names)
        self._children = {n: [] for n in names}
        for n in names:
            p = self.parent(n)
            if p is not None:
                if p not in known:
                    raise ValueError(f"parent {p!r} of {n!r} is not declared")
                self._children[p].append(n)
        self._initials = dict(initials or {})
        for comp, child in self._initials.items():
            if comp not in known or child not in self._children.get(comp, ()):
                raise ValueError(f"bad initial {child!r} for {comp!r}")
        for n, kids in self._children.items():
            if kids and n not in self._initials:
                raise ValueError(f"composite state {n!r} needs an initial child")

    def check(self, name):
        if name not in self.names:
            raise ValueError(f"unknown state {name!r}")
        return name

    @staticmethod
    def parent(name):
        return name.rpartition(".")[0] or None

    def lineage(self, name):
        """``name`` and its ancestors, innermost first."""
        out = [name]
        while self.parent(out[-1]) is not None:
            out.append(self.parent(out[-1]))
        return out

    def descent(self, name):
        """``name`` followed by its chain of initial children down to a leaf."""
        out = [name]
        while out[-1] in self._initials:
            out.append(self._initials[out[-1]])
        return out

    def lca(self, a, b):
        """Deepest state that is a proper ancestor of both ``a`` and ``b`` (or None)."""
        above_a = set(self.lineage(a)[1:])
        for cand in self.lineage(b)[1:]:
            if cand in above_a:
                return cand
        return None
