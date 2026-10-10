import io
import os
import tempfile
import unittest

from buildplan import CycleError, Graph, GraphError, SpecError, parse_spec, topo_order
from buildplan.cli import main


class Basics(unittest.TestCase):
    def test_order(self):
        g = parse_spec("app: lib util\nlib: core\nutil: core\ncore:\n")
        order = topo_order(g)
        for node in g.nodes():
            for dep in g.deps(node):
                self.assertLess(order.index(dep), order.index(node))

    def test_cycle(self):
        g = Graph()
        g.add_dep("a", "b")
        g.add_dep("b", "a")
        with self.assertRaises(CycleError):
            topo_order(g)

    def test_missing(self):
        g = Graph()
        g.add_dep("a", "zzz")
        with self.assertRaises(GraphError):
            topo_order(g)

    def test_spec_errors(self):
        for bad in ("a b\n", "a: b\na:\n", "a: b!c\n"):
            with self.assertRaises(SpecError):
                parse_spec(bad)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "spec.txt")
            with open(path, "w") as fh:
                fh.write("b: a\na:\n")
            out, err = io.StringIO(), io.StringIO()
            self.assertEqual(main([path], out, err), 0)
            self.assertEqual(out.getvalue().split(), ["a", "b"])
            self.assertEqual(main([os.path.join(d, "nope")], out, err), 2)


if __name__ == "__main__":
    unittest.main()
