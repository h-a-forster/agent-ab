"""The dependency graph."""


class GraphError(Exception):
    pass


class Graph:
    def __init__(self):
        self._deps = {}  # node -> {dep: optional?}

    def add_node(self, name):
        self._deps.setdefault(name, {})

    def add_dep(self, node, dep, optional=False):
        """``node`` depends on ``dep``. Creates ``node`` if needed (not ``dep``).

        Declaring the same dependency both ways makes it required.
        """
        self.add_node(node)
        self._deps[node][dep] = self._deps[node].get(dep, True) and optional

    def nodes(self):
        return list(self._deps)

    def __contains__(self, name):
        return name in self._deps

    def deps(self, node):
        """Required dependencies."""
        return [d for d, opt in self._deps[node].items() if not opt]

    def optional_deps(self, node):
        return [d for d, opt in self._deps[node].items() if opt]

    def all_deps(self, node):
        return list(self._deps[node])
