"""Build ordering."""

from .cycles import CycleError
from .graph import GraphError


def topo_order(graph):
    """All nodes, every node after its dependencies."""
    for node in graph.nodes():
        for dep in graph.deps(node):
            if dep not in graph:
                raise GraphError(f"missing dependency {dep!r} of {node!r}")
    done, active, out = set(), set(), []

    def visit(node):
        if node in done:
            return
        if node in active:
            raise CycleError("dependency cycle")
        active.add(node)
        for dep in graph.deps(node):
            visit(dep)
        active.discard(node)
        done.add(node)
        out.append(node)

    for node in graph.nodes():
        visit(node)
    return out
