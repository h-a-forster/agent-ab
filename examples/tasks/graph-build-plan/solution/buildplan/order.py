"""Build ordering."""

import heapq

from .cycles import CycleError, find_cycle
from .graph import GraphError


def build_set(graph, targets=None):
    """Nodes to build: all of them, or the required-dependency closure of ``targets``."""
    if targets is None:
        chosen = set(graph.nodes())
    else:
        targets = list(targets)
        unknown = sorted(t for t in set(targets) if t not in graph)
        if unknown:
            raise GraphError(f"unknown target {unknown[0]!r}")
        chosen = set()
        stack = list(targets)
        while stack:
            node = stack.pop()
            if node in chosen:
                continue
            chosen.add(node)
            stack.extend(d for d in graph.deps(node) if d in graph)
    missing = sorted((n, d) for n in chosen for d in graph.deps(n) if d not in graph)
    if missing:
        node, dep = missing[0]
        raise GraphError(f"missing dependency {dep!r} of {node!r}")
    return chosen


def _edges(graph, chosen):
    return {n: {d for d in graph.all_deps(n) if d in chosen} for n in chosen}


def _kahn(chosen, edges):
    dependents = {n: [] for n in chosen}
    pending = {}
    for n in chosen:
        pending[n] = len(edges[n])
        for d in edges[n]:
            dependents[d].append(n)
    ready = [n for n in chosen if pending[n] == 0]
    heapq.heapify(ready)
    out = []
    while ready:
        n = heapq.heappop(ready)
        out.append(n)
        for m in dependents[n]:
            pending[m] -= 1
            if pending[m] == 0:
                heapq.heappush(ready, m)
    if len(out) != len(chosen):
        stuck = {n for n in chosen if pending[n] > 0}
        sub = {n: {d for d in edges[n] if d in stuck} for n in stuck}
        raise CycleError(find_cycle(stuck, sub))
    return out


def topo_order(graph, targets=None):
    """Dependencies first; ties are broken by smallest name."""
    chosen = build_set(graph, targets)
    return _kahn(chosen, _edges(graph, chosen))


def levels(graph, targets=None):
    """Parallel build batches: a node's level is 1 + the highest level of its dependencies."""
    chosen = build_set(graph, targets)
    edges = _edges(graph, chosen)
    level = {}
    for n in _kahn(chosen, edges):
        level[n] = 1 + max((level[d] for d in edges[n]), default=-1)
    out = [[] for _ in range(max(level.values(), default=-1) + 1)]
    for n in sorted(level):
        out[level[n]].append(n)
    return out


def reverse_deps(graph, node):
    """Sorted list of every node that depends on ``node``, directly or not."""
    if node not in graph:
        raise GraphError(f"unknown node {node!r}")
    users = {}
    for n in graph.nodes():
        for d in graph.all_deps(n):
            users.setdefault(d, []).append(n)
    seen, stack = set(), [node]
    while stack:
        for u in users.get(stack.pop(), ()):
            if u not in seen:
                seen.add(u)
                stack.append(u)
    seen.discard(node)
    return sorted(seen)


def affected(graph, changed):
    """Build order for the changed nodes plus everything that depends on them."""
    changed = list(changed)
    unknown = sorted(c for c in set(changed) if c not in graph)
    if unknown:
        raise GraphError(f"unknown node {unknown[0]!r}")
    chosen = set(changed)
    for c in changed:
        chosen.update(reverse_deps(graph, c))
    return _kahn(chosen, _edges(graph, chosen))
