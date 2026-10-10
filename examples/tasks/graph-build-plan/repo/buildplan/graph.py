"""The dependency graph."""


class GraphError(Exception):
    pass


class Graph:
    def __init__(self):
        self._deps = {}  # node -> list of deps, in insertion order

    def add_node(self, name):
        self._deps.setdefault(name, [])

    def add_dep(self, node, dep):
        """``node`` depends on ``dep``. Creates ``node`` if needed (not ``dep``)."""
        self.add_node(node)
        if dep not in self._deps[node]:
            self._deps[node].append(dep)

    def nodes(self):
        return list(self._deps)

    def __contains__(self, name):
        return name in self._deps

    def deps(self, node):
        return list(self._deps[node])
