"""Human readable views of a resolution."""

from .graph import dependency_map, dependents


def format_resolution(resolution):
    """One ``name version`` line per package, names padded to a common width."""
    names = resolution.names()
    if not names:
        return "(nothing)"
    width = max(len(n) for n in names)
    return "\n".join("%s  %s" % (n.ljust(width), resolution[n]) for n in names)


def explain(resolution, index, name):
    """Why a package is in the resolution: its version and who depends on it."""
    if name not in resolution:
        return "%s is not installed" % name
    users = dependents(resolution, index, name)
    head = "%s@%s" % (name, resolution[name])
    if not users:
        return head + " (required directly)"
    return head + " (required by %s)" % ", ".join("%s@%s" % (u, resolution[u]) for u in users)


def tree(resolution, index, roots):
    """Indented dependency tree below ``roots`` (repeated subtrees are marked ``(*)``)."""
    deps = dependency_map(resolution, index)
    seen = set()
    lines = []

    def walk(name, level):
        label = "%s@%s" % (name, resolution[name])
        if name in seen:
            lines.append("%s%s (*)" % ("  " * level, label))
            return
        seen.add(name)
        lines.append("%s%s" % ("  " * level, label))
        for dep in deps[name]:
            walk(dep, level + 1)

    for root in sorted(roots):
        if root in resolution:
            walk(root, 0)
    return "\n".join(lines)


def install_plan(resolution, index):
    """Numbered install steps in dependency order, e.g. ``1. left@1.0.0``."""
    from .graph import install_order

    return "\n".join("%d. %s@%s" % (i, n, resolution[n]) for i, n in enumerate(install_order(resolution, index), 1))


def outdated(resolution, index):
    """``[(name, current, latest_stable)]`` for packages with a newer stable release."""
    rows = []
    for name, version in resolution.items():
        stable = [v for v in index.versions(name) if not v.pre]
        if stable and stable[0] > version:
            rows.append((name, version, stable[0]))
    return rows
