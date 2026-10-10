import io
import os
import tempfile
import unittest

from buildplan import (CycleError, Graph, GraphError, SpecError, affected, levels, parse_spec,
                       reverse_deps, topo_order)
from buildplan.cli import main


def graph(spec):
    return parse_spec(spec)


DIAMOND = graph("app: lib util\nlib: core\nutil: core\ncore:\nzeta:\ndocs: app\n")


class Ordering(unittest.TestCase):
    def test_smallest_ready_first(self):
        self.assertEqual(topo_order(DIAMOND), ["core", "lib", "util", "app", "docs", "zeta"])

    def test_not_insertion_order(self):
        g = graph("z:\ny:\nx: z\nb:\na: b\n")
        self.assertEqual(topo_order(g), ["b", "a", "y", "z", "x"])

    def test_targets_closure(self):
        self.assertEqual(topo_order(DIAMOND, ["lib"]), ["core", "lib"])
        self.assertEqual(topo_order(DIAMOND, ["util", "lib"]), ["core", "lib", "util"])
        self.assertEqual(topo_order(DIAMOND, ["docs"]), ["core", "lib", "util", "app", "docs"])

    def test_targets_empty_list_is_empty(self):
        self.assertEqual(topo_order(DIAMOND, []), [])

    def test_duplicate_targets(self):
        self.assertEqual(topo_order(DIAMOND, ["lib", "lib"]), ["core", "lib"])

    def test_unknown_target(self):
        with self.assertRaises(GraphError) as cm:
            topo_order(DIAMOND, ["lib", "zzz", "yyy"])
        self.assertIn("yyy", str(cm.exception))

    def test_missing_dependency_reported_smallest(self):
        g = Graph()
        g.add_dep("b", "ghost2")
        g.add_dep("a", "ghost9")
        g.add_dep("a", "ghost1")
        with self.assertRaises(GraphError) as cm:
            topo_order(g)
        self.assertEqual(str(cm.exception), "missing dependency 'ghost1' of 'a'")

    def test_missing_dependency_outside_targets_is_fine(self):
        g = Graph()
        g.add_dep("a", "ghost")
        g.add_node("b")
        self.assertEqual(topo_order(g, ["b"]), ["b"])
        with self.assertRaises(GraphError):
            topo_order(g, ["a"])

    def test_graph_api(self):
        g = Graph()
        g.add_dep("a", "b")
        g.add_dep("a", "c", optional=True)
        g.add_dep("a", "d", optional=True)
        g.add_dep("a", "d")
        g.add_dep("a", "c", optional=True)
        self.assertEqual(g.deps("a"), ["b", "d"])
        self.assertEqual(g.optional_deps("a"), ["c"])
        self.assertEqual(sorted(g.all_deps("a")), ["b", "c", "d"])
        g.add_dep("a", "b", optional=True)
        self.assertEqual(g.deps("a"), ["b", "d"])

    def test_deep_chain_is_fast_and_iterative(self):
        n = 100_000
        g = Graph()
        for i in range(n - 1):
            g.add_dep(f"n{i:06d}", f"n{i + 1:06d}")
        g.add_node(f"n{n - 1:06d}")
        order = topo_order(g)
        self.assertEqual(order[0], f"n{n - 1:06d}")
        self.assertEqual(order[-1], "n000000")
        self.assertEqual(len(order), n)
        self.assertEqual(len(topo_order(g, ["n099990"])), 10)

    def test_wide_graph(self):
        g = Graph()
        for i in range(20000):
            g.add_dep("root", f"leaf{i:05d}")
            g.add_node(f"leaf{i:05d}")
        order = topo_order(g)
        self.assertEqual(order[-1], "root")
        self.assertEqual(order[0], "leaf00000")


class Optional(unittest.TestCase):
    def test_optional_ignored_when_not_in_set(self):
        g = graph("app: ?plugin core\ncore:\nplugin: core\n")
        self.assertEqual(topo_order(g, ["app"]), ["core", "app"])

    def test_optional_orders_when_in_set(self):
        g = graph("app: ?plugin core\ncore:\nplugin: core\n")
        self.assertEqual(topo_order(g), ["core", "plugin", "app"])
        self.assertEqual(topo_order(g, ["app", "plugin"]), ["core", "plugin", "app"])

    def test_optional_changes_tie_break(self):
        g = graph("a: ?z\nz:\n")
        self.assertEqual(topo_order(g), ["z", "a"])
        self.assertEqual(topo_order(g, ["a"]), ["a"])

    def test_optional_dep_may_be_missing_from_graph(self):
        g = graph("a: ?ghost b\nb:\n")
        self.assertEqual(topo_order(g), ["b", "a"])

    def test_required_dep_pulls_into_set_even_if_declared_optional_elsewhere(self):
        g = graph("a: b\nc: ?b\nb:\n")
        self.assertEqual(topo_order(g, ["c"]), ["c"])
        self.assertEqual(topo_order(g, ["a", "c"]), ["b", "a", "c"])

    def test_optional_edge_can_make_cycle(self):
        g = graph("a: b\nb: ?a\n")
        with self.assertRaises(CycleError) as cm:
            topo_order(g)
        self.assertEqual(cm.exception.cycle, ["a", "b", "a"])
        self.assertEqual(topo_order(g, ["b"]), ["b"])

    def test_spec_optional_tokens(self):
        for bad in ("a: ?\n", "a: ??x\n", "a: ?b!\n"):
            with self.assertRaises(SpecError):
                parse_spec(bad)
        g = parse_spec("a: ?b b\n")
        self.assertEqual(g.deps("a"), ["b"])
        self.assertEqual(g.optional_deps("a"), [])


class Cycles(unittest.TestCase):
    def cycle(self, spec, targets=None):
        with self.assertRaises(CycleError) as cm:
            topo_order(graph(spec), targets)
        return cm.exception

    def test_simple_cycle_and_message(self):
        e = self.cycle("a: b\nb: c\nc: a\n")
        self.assertEqual(e.cycle, ["a", "b", "c", "a"])
        self.assertEqual(str(e), "dependency cycle: a -> b -> c -> a")

    def test_rotated_to_smallest(self):
        e = self.cycle("x: y\ny: z\nz: x\n")
        self.assertEqual(e.cycle, ["x", "y", "z", "x"])
        e = self.cycle("m: b\nb: c\nc: m\n")
        self.assertEqual(e.cycle, ["b", "c", "m", "b"])

    def test_self_loop(self):
        self.assertEqual(self.cycle("a: a\n").cycle, ["a", "a"])

    def test_dependents_of_cycle_not_reported(self):
        e = self.cycle("a: x\nx: y\ny: x\n")
        self.assertEqual(e.cycle, ["x", "y", "x"])

    def test_dependencies_of_cycle_not_reported(self):
        e = self.cycle("x: y base\ny: x\nbase:\n")
        self.assertEqual(e.cycle, ["x", "y", "x"])

    def test_smallest_node_on_any_cycle(self):
        e = self.cycle("p: q\nq: p\nc: d\nd: c\n")
        self.assertEqual(e.cycle, ["c", "d", "c"])

    def test_shortest_through_start(self):
        e = self.cycle("a: b c\nb: d\nd: e\ne: a\nc: a\n")
        self.assertEqual(e.cycle, ["a", "c", "a"])

    def test_lexicographically_smallest_among_equal(self):
        e = self.cycle("a: c b\nb: a\nc: a\n")
        self.assertEqual(e.cycle, ["a", "b", "a"])
        e = self.cycle("a: c d\nc: e\nd: e\ne: a\n")
        self.assertEqual(e.cycle, ["a", "c", "e", "a"])

    def test_cycle_inside_inner_loop(self):
        # a is on the big cycle; b<->c is an inner loop not through a
        e = self.cycle("a: b\nb: c d\nc: b\nd: a\n")
        self.assertEqual(e.cycle, ["a", "b", "d", "a"])

    def test_cycles_outside_targets_ignored(self):
        spec = "ok: base\nbase:\nloop1: loop2\nloop2: loop1\n"
        self.assertEqual(topo_order(graph(spec), ["ok"]), ["base", "ok"])
        e = self.cycle(spec)
        self.assertEqual(e.cycle, ["loop1", "loop2", "loop1"])

    def test_cycle_error_is_graph_error(self):
        self.assertTrue(issubclass(CycleError, GraphError))

    def test_long_chain_into_cycle_is_fast(self):
        n = 50_000
        g = Graph()
        for i in range(n):
            g.add_dep(f"a{i:06d}", f"a{i + 1:06d}" if i < n - 1 else "z1")
        g.add_dep("z1", "z2")
        g.add_dep("z2", "z3")
        g.add_dep("z3", "z1")
        with self.assertRaises(CycleError) as cm:
            topo_order(g)
        self.assertEqual(cm.exception.cycle, ["z1", "z2", "z3", "z1"])

    def test_levels_cycle(self):
        with self.assertRaises(CycleError):
            levels(graph("a: b\nb: a\n"))


class Levels(unittest.TestCase):
    def test_diamond(self):
        self.assertEqual(levels(DIAMOND), [["core", "zeta"], ["lib", "util"], ["app"], ["docs"]])

    def test_longest_path_decides(self):
        g = graph("a: b c\nb: c\nc:\nd: a\ne:\n")
        self.assertEqual(levels(g), [["c", "e"], ["b"], ["a"], ["d"]])

    def test_targets(self):
        self.assertEqual(levels(DIAMOND, ["lib", "zeta"]), [["core", "zeta"], ["lib"]])

    def test_empty(self):
        self.assertEqual(levels(Graph()), [])
        self.assertEqual(levels(DIAMOND, []), [])

    def test_optional_only_when_present(self):
        g = graph("a: ?b\nb:\n")
        self.assertEqual(levels(g), [["b"], ["a"]])
        self.assertEqual(levels(g, ["a"]), [["a"]])

    def test_errors(self):
        with self.assertRaises(GraphError):
            levels(DIAMOND, ["nope"])

    def test_deep_chain(self):
        g = Graph()
        for i in range(30000):
            g.add_dep(f"n{i}", f"n{i + 1}")
        g.add_node("n30000")
        lv = levels(g)
        self.assertEqual(len(lv), 30001)
        self.assertEqual(lv[0], ["n30000"])


class ReverseAndAffected(unittest.TestCase):
    def test_reverse_deps(self):
        self.assertEqual(reverse_deps(DIAMOND, "core"), ["app", "docs", "lib", "util"])
        self.assertEqual(reverse_deps(DIAMOND, "docs"), [])
        self.assertEqual(reverse_deps(DIAMOND, "util"), ["app", "docs"])

    def test_reverse_deps_includes_optional(self):
        g = graph("a: ?b\nb:\nc: a\n")
        self.assertEqual(reverse_deps(g, "b"), ["a", "c"])

    def test_reverse_deps_excludes_self_in_cycle(self):
        g = graph("a: b\nb: a\nc: a\n")
        self.assertEqual(reverse_deps(g, "a"), ["b", "c"])

    def test_reverse_unknown(self):
        with self.assertRaises(GraphError):
            reverse_deps(DIAMOND, "nope")

    def test_affected(self):
        self.assertEqual(affected(DIAMOND, ["lib"]), ["lib", "app", "docs"])
        self.assertEqual(affected(DIAMOND, ["core"]), ["core", "lib", "util", "app", "docs"])
        self.assertEqual(affected(DIAMOND, ["lib", "util"]), ["lib", "util", "app", "docs"])
        self.assertEqual(affected(DIAMOND, ["zeta", "docs"]), ["docs", "zeta"])

    def test_affected_ignores_unrelated_missing(self):
        g = Graph()
        g.add_dep("a", "ghost")
        g.add_dep("b", "a")
        g.add_node("c")
        self.assertEqual(affected(g, ["c"]), ["c"])

    def test_affected_unknown(self):
        with self.assertRaises(GraphError) as cm:
            affected(DIAMOND, ["lib", "nope"])
        self.assertIn("nope", str(cm.exception))

    def test_affected_cycle(self):
        g = graph("a: b\nb: a\nc: a\n")
        with self.assertRaises(CycleError):
            affected(g, ["c", "a"])
        self.assertEqual(affected(g, ["c"]), ["c"])

    def test_affected_through_optional(self):
        g = graph("a: ?b\nb:\n")
        self.assertEqual(affected(g, ["b"]), ["b", "a"])

    def test_affected_empty(self):
        self.assertEqual(affected(DIAMOND, []), [])


class Cli(unittest.TestCase):
    def run_cli(self, spec, *args, raw_args=None):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "spec.txt")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(spec)
            argv = list(raw_args) if raw_args is not None else list(args)
            argv = [path if a == "SPEC" else a for a in argv]
            out, err = io.StringIO(), io.StringIO()
            code = main(argv, out, err)
            return code, out.getvalue(), err.getvalue()

    SPEC = "app: lib ?plug\nlib: core\nplug: core\ncore:\n"

    def test_default(self):
        self.assertEqual(self.run_cli(self.SPEC, "SPEC"), (0, "core\nlib\nplug\napp\n", ""))

    def test_targets_both_forms_any_position(self):
        self.assertEqual(self.run_cli(self.SPEC, "--target", "app", "SPEC")[1], "core\nlib\napp\n")
        self.assertEqual(self.run_cli(self.SPEC, "SPEC", "--target=lib")[1], "core\nlib\n")
        self.assertEqual(self.run_cli(self.SPEC, "--target", "plug", "SPEC", "--target=lib")[1], "core\nlib\nplug\n")

    def test_levels(self):
        self.assertEqual(self.run_cli(self.SPEC, "--levels", "SPEC")[1], "0: core\n1: lib plug\n2: app\n")
        self.assertEqual(self.run_cli(self.SPEC, "SPEC", "--levels", "--target", "app")[1], "0: core\n1: lib\n2: app\n")

    def test_affected(self):
        self.assertEqual(self.run_cli(self.SPEC, "--affected", "plug", "SPEC"), (0, "plug\napp\n", ""))
        self.assertEqual(self.run_cli(self.SPEC, "--affected=core", "--affected", "lib", "SPEC")[1],
                         "core\nlib\nplug\napp\n")

    def test_error_cases(self):
        cases = [
            (("--target", "SPEC"), "error:"),
            (("--bogus", "SPEC"), "bogus"),
            (("--affected", "core", "--target", "app", "SPEC"), "error:"),
            (("--affected", "core", "--levels", "SPEC"), "error:"),
            ((), "error:"),
            (("--target",), "error:"),
            (("--target", "zzz", "SPEC"), "zzz"),
            (("--affected", "zzz", "SPEC"), "zzz"),
        ]
        for args, needle in cases:
            with self.subTest(args=args):
                code, out, err = self.run_cli(self.SPEC, raw_args=args)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertTrue(err.startswith("error: "), err)
                self.assertIn(needle, err)

    def test_two_specs(self):
        code, out, err = self.run_cli(self.SPEC, raw_args=("SPEC", "SPEC"))
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error: "))

    def test_cycle_message(self):
        code, out, err = self.run_cli("a: b\nb: a\n", "SPEC")
        self.assertEqual((code, out, err), (2, "", "error: dependency cycle: a -> b -> a\n"))

    def test_missing_dep_message(self):
        code, out, err = self.run_cli("a: ghost\n", "SPEC")
        self.assertEqual((code, err), (2, "error: missing dependency 'ghost' of 'a'\n"))

    def test_spec_error(self):
        code, out, err = self.run_cli("a: b\n\nbroken line\n", "SPEC")
        self.assertEqual(code, 2)
        self.assertIn("line 3", err)

    def test_unreadable_file(self):
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(main(["/definitely/not/here.txt"], out, err), 2)
        self.assertTrue(err.getvalue().startswith("error: "))

    def test_optional_in_spec_via_cli(self):
        code, out, err = self.run_cli("a: ?ghost\n", "SPEC")
        self.assertEqual((code, out), (0, "a\n"))


if __name__ == "__main__":
    unittest.main()
