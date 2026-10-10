"""Backtracking dependency resolution."""

from .errors import ResolutionError
from .specifier import parse_range
from .version import Version


class Resolution:
    """The chosen version per package name."""

    def __init__(self, chosen):
        self._chosen = dict(chosen)

    def __getitem__(self, name):
        return self._chosen[name]

    def __contains__(self, name):
        return name in self._chosen

    def __len__(self):
        return len(self._chosen)

    def names(self):
        return sorted(self._chosen)

    def items(self):
        return [(n, self._chosen[n]) for n in self.names()]

    def as_dict(self):
        return dict(self._chosen)

    def __eq__(self, other):
        if isinstance(other, Resolution):
            return self._chosen == other._chosen
        if isinstance(other, dict):
            return self._chosen == {k: Version.parse(v) for k, v in other.items()}
        return NotImplemented

    def __repr__(self):
        return "Resolution(%s)" % ", ".join("%s@%s" % kv for kv in self.items())


def resolve(index, requirements):
    """Pick one version per needed package so every requirement holds.

    ``requirements`` maps a package name to a range (text or ``Range``).  Packages are
    decided in alphabetical order; for each, the highest matching version is tried first and
    the search backtracks when a choice leads to a dead end.
    """
    constraints = {name: [parse_range(rng)] for name, rng in requirements.items()}
    failed = []
    result = _solve(index, {}, constraints, failed)
    if result is None:
        name = failed[-1] if failed else None
        raise ResolutionError("cannot satisfy requirements (stuck on %s)" % name, name)
    return Resolution(result)


def _solve(index, chosen, constraints, failed):
    pending = sorted(n for n in constraints if n not in chosen)
    if not pending:
        return chosen
    name = pending[0]
    candidates = index.candidates(name, constraints[name])
    if not candidates:
        failed.append(name)
        return None
    for release in candidates:
        new_chosen = dict(chosen)
        new_chosen[name] = release.version
        new_constraints = constraints
        compatible = True
        for dep, rng in release.deps.items():
            new_constraints.setdefault(dep, []).append(rng)
            if dep in new_chosen and not rng.matches(new_chosen[dep]):
                compatible = False
                break
        if not compatible:
            failed.append(name)
            continue
        result = _solve(index, new_chosen, new_constraints, failed)
        if result is not None:
            return result
    return None
