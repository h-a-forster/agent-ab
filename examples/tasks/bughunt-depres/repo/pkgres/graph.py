"""Dependency graph of a resolution: install order, dependents, cycles."""

import heapq

from .errors import CycleError


def dependency_map(resolution, index):
    """``{name: sorted list of dependency names}`` restricted to resolved packages."""
    out = {}
    for name, version in resolution.items():
        release = index.release(name, version)
        out[name] = sorted(d for d in release.deps if d in resolution)
    return out


def dependents(resolution, index, name):
    """Names of resolved packages that directly depend on ``name``."""
    deps = dependency_map(resolution, index)
    return sorted(n for n, ds in deps.items() if name in ds)


def find_cycle(deps):
    """A list ``[a, b, ..., a]`` describing one cycle, or ``None``."""
    state = {}
    stack = []

    def visit(node):
        state[node] = 1
        stack.append(node)
        for nxt in deps.get(node, ()):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(deps):
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def install_order(resolution, index):
    """Dependencies before dependents.

    Among packages that can be installed at the same moment the alphabetically smallest
    comes first, so the result is the lexicographically smallest valid order.
    """
    deps = dependency_map(resolution, index)
    cycle = find_cycle(deps)
    if cycle:
        raise CycleError(cycle)
    remaining = {n: set(ds) for n, ds in deps.items()}
    users = {n: [] for n in deps}
    for n, ds in deps.items():
        for d in ds:
            users[d].append(n)
    ready = sorted(n for n, ds in remaining.items() if not ds)
    order = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for user in users[node]:
            remaining[user].discard(node)
            if not remaining[user]:
                ready.append(user)
    return order


def depth(resolution, index, name):
    """Length of the longest dependency chain below ``name`` (0 for a leaf)."""
    deps = dependency_map(resolution, index)
    memo = {}

    def walk(n):
        if n not in memo:
            memo[n] = 0 if not deps[n] else 1 + max(walk(d) for d in deps[n])
        return memo[n]

    return walk(name)
