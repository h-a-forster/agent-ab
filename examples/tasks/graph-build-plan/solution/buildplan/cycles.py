"""Cycle detection and errors."""

from collections import deque

from .graph import GraphError


class CycleError(GraphError):
    def __init__(self, cycle):
        self.cycle = list(cycle)
        super().__init__("dependency cycle: " + " -> ".join(self.cycle))


def _sccs(nodes, edges):
    """Iterative Tarjan; returns a list of components (lists of nodes)."""
    index, low, on_stack, stack, out = {}, {}, set(), [], []
    counter = 0
    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(sorted(edges[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(edges[nxt]))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    top = stack.pop()
                    on_stack.discard(top)
                    comp.append(top)
                    if top == node:
                        break
                out.append(comp)
    return out


def find_cycle(nodes, edges):
    """Shortest cycle through the smallest node that lies on any cycle (lexicographically
    smallest among equally short ones), as ``[n0, n1, ..., n0]``; None if acyclic."""
    on_cycle = []
    for comp in _sccs(nodes, edges):
        if len(comp) > 1 or comp[0] in edges[comp[0]]:
            on_cycle.extend(comp)
    if not on_cycle:
        return None
    start = min(on_cycle)
    parent = {}
    queue = deque([start])
    seen = {start}
    while queue:
        node = queue.popleft()
        for nxt in sorted(edges[node]):
            if nxt == start:
                path = [node]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path + [start]
            if nxt not in seen:
                seen.add(nxt)
                parent[nxt] = node
                queue.append(nxt)
    return None
