import unittest

from hsm import Machine, Transition

STATES = ["off", "on", "on.stopped", "on.playing", "on.playing.normal", "on.playing.fast", "on.paused"]
INITIALS = {"on": "on.stopped", "on.playing": "on.playing.normal"}


def build(extra=(), initial="off", log=None, states=STATES, initials=INITIALS, **kw):
    log = [] if log is None else log
    names = [s for s in states]
    enter = {n: (lambda p, n=n: log.append("+" + n)) for n in names}
    exit_ = {n: (lambda p, n=n: log.append("-" + n)) for n in names}
    ts = [
        Transition("off", "power", "on", action=lambda p: log.append("act:power")),
        Transition("on", "power", "off", action=lambda p: log.append("act:off")),
        Transition("on.stopped", "play", "on.playing", action=lambda p: log.append("act:play")),
        Transition("on.playing", "pause", "on.paused"),
        Transition("on.paused", "play", "on.playing"),
        Transition("on.playing.normal", "ff", "on.playing.fast"),
        Transition("on.playing.fast", "ff", "on.playing.normal"),
    ] + list(extra)
    m = Machine(states, ts, initial, on_enter=enter, on_exit=exit_, initials=initials, **kw)
    return m, log


class Declaration(unittest.TestCase):
    def test_missing_parent(self):
        with self.assertRaises(ValueError):
            Machine(["a.b"], [], "a.b")

    def test_composite_needs_initial(self):
        with self.assertRaises(ValueError):
            Machine(["a", "a.b"], [], "a.b")
        with self.assertRaises(ValueError):
            Machine(["a", "a.b", "a.c"], [], "a.b", initials={})

    def test_initial_must_be_direct_child(self):
        with self.assertRaises(ValueError):
            Machine(["a", "a.b", "a.b.c"], [], "a", initials={"a": "a.b.c", "a.b": "a.b.c"})
        with self.assertRaises(ValueError):
            Machine(["a", "a.b", "x"], [], "a", initials={"a": "x"})

    def test_initial_entry_for_unknown_or_leaf(self):
        with self.assertRaises(ValueError):
            Machine(["a", "a.b"], [], "a", initials={"a": "a.b", "zzz": "a.b"})
        with self.assertRaises(ValueError):
            Machine(["a", "a.b"], [], "a", initials={"a": "a.b", "a.b": "a"})

    def test_duplicates_and_unknown_still_rejected(self):
        with self.assertRaises(ValueError):
            Machine(["a", "a"], [], "a")
        with self.assertRaises(ValueError):
            Machine(["a"], [Transition("a", "e", "nope")], "a")

    def test_flat_machines_need_no_initials(self):
        m = Machine(["x", "y"], [Transition("x", "go", "y")], "x")
        self.assertTrue(m.send("go"))
        self.assertEqual(m.state, "y")
        self.assertEqual(m.configuration(), ["y"])


class Entering(unittest.TestCase):
    def test_initial_composite_descends_and_logs(self):
        m, log = build(initial="on.playing")
        self.assertEqual(m.state, "on.playing.normal")
        self.assertEqual(log, ["+on", "+on.playing", "+on.playing.normal"])

    def test_initial_leaf_enters_ancestors_first(self):
        m, log = build(initial="on.paused")
        self.assertEqual(m.state, "on.paused")
        self.assertEqual(log, ["+on", "+on.paused"])

    def test_configuration_and_is_in(self):
        m, _ = build(initial="on.playing")
        self.assertEqual(m.configuration(), ["on", "on.playing", "on.playing.normal"])
        for name in ("on", "on.playing", "on.playing.normal"):
            self.assertTrue(m.is_in(name))
        self.assertFalse(m.is_in("on.paused"))
        self.assertFalse(m.is_in("off"))

    def test_top_level_leaf(self):
        m, log = build()
        self.assertEqual(m.configuration(), ["off"])
        self.assertEqual(log, ["+off"])


class Transitions(unittest.TestCase):
    def test_enter_composite_target(self):
        m, log = build()
        del log[:]
        self.assertTrue(m.send("power"))
        self.assertEqual(m.state, "on.stopped")
        self.assertEqual(log, ["-off", "act:power", "+on", "+on.stopped"])

    def test_sibling_leaf_transition_keeps_parent(self):
        m, log = build(initial="on")
        del log[:]
        m.send("play")
        self.assertEqual(m.state, "on.playing.normal")
        self.assertEqual(log, ["-on.stopped", "act:play", "+on.playing", "+on.playing.normal"])

    def test_inherited_transition_exits_whole_chain(self):
        m, log = build(initial="on.playing")
        del log[:]
        m.send("power")  # declared on "on", active leaf is on.playing.normal
        self.assertEqual(m.state, "off")
        self.assertEqual(log, ["-on.playing.normal", "-on.playing", "-on", "act:off", "+off"])

    def test_inherited_from_middle_state(self):
        m, log = build(initial="on.playing.fast")
        del log[:]
        m.send("pause")  # declared on on.playing; LCA with on.paused is "on"
        self.assertEqual(m.state, "on.paused")
        self.assertEqual(log, ["-on.playing.fast", "-on.playing", "+on.paused"])

    def test_inner_overrides_outer(self):
        extra = [Transition("on.playing.normal", "power", "on.paused", action=lambda p: None)]
        m, log = build(extra, initial="on.playing")
        m.send("power")
        self.assertEqual(m.state, "on.paused")

    def test_failing_guard_falls_back_to_next_then_outer(self):
        extra = [
            Transition("on.playing.normal", "x", "on.paused", guard=lambda p: False),
            Transition("on.playing.normal", "x", "on.playing.fast", guard=lambda p: p.get("n", 0) > 1),
            Transition("on", "x", "off"),
        ]
        m, _ = build(extra, initial="on.playing")
        m.send("x", n=5)
        self.assertEqual(m.state, "on.playing.fast")
        m, _ = build(extra, initial="on.playing")
        m.send("x", n=0)
        self.assertEqual(m.state, "off")

    def test_all_guards_fail_returns_false(self):
        extra = [Transition("on.stopped", "x", "off", guard=lambda p: False),
                 Transition("on", "x", "off", guard=lambda p: False)]
        m, log = build(extra, initial="on")
        del log[:]
        self.assertFalse(m.send("x"))
        self.assertEqual(m.state, "on.stopped")
        self.assertEqual(log, [])

    def test_unknown_event(self):
        m, _ = build()
        self.assertFalse(m.send("nope"))

    def test_declaration_order_wins(self):
        extra = [Transition("on.stopped", "y", "on.paused"), Transition("on.stopped", "y", "off")]
        m, _ = build(extra, initial="on")
        m.send("y")
        self.assertEqual(m.state, "on.paused")

    def test_payload_reaches_everything(self):
        seen = []
        extra = [Transition("on.stopped", "z", "on.paused", guard=lambda p: seen.append(("g", p)) or True,
                            action=lambda p: seen.append(("a", p)))]
        enter = {"on.paused": lambda p: seen.append(("e", p))}
        exit_ = {"on.stopped": lambda p: seen.append(("x", p))}
        m = Machine(STATES, extra, "on", on_enter=enter, on_exit=exit_, initials=INITIALS)
        m.send("z", k=1)
        self.assertEqual([t for t, _ in seen], ["g", "x", "a", "e"])
        self.assertTrue(all(p == {"k": 1} for _, p in seen))


class SelfAndRelated(unittest.TestCase):
    def test_leaf_self_transition(self):
        extra = [Transition("on.paused", "again", "on.paused")]
        m, log = build(extra, initial="on.paused")
        del log[:]
        m.send("again")
        self.assertEqual(log, ["-on.paused", "+on.paused"])

    def test_composite_self_transition_resets_descendants(self):
        extra = [Transition("on.playing", "restart", "on.playing")]
        m, log = build(extra, initial="on.playing.fast")
        del log[:]
        m.send("restart")
        self.assertEqual(m.state, "on.playing.normal")
        self.assertEqual(log, ["-on.playing.fast", "-on.playing", "+on.playing", "+on.playing.normal"])

    def test_self_transition_declared_on_ancestor_of_leaf(self):
        extra = [Transition("on", "reset", "on")]
        m, log = build(extra, initial="on.paused")
        del log[:]
        m.send("reset")
        self.assertEqual(m.state, "on.stopped")
        self.assertEqual(log, ["-on.paused", "-on", "+on", "+on.stopped"])

    def test_parent_to_own_child_is_external(self):
        extra = [Transition("on", "dive", "on.playing.fast")]
        m, log = build(extra, initial="on.paused")
        del log[:]
        m.send("dive")
        self.assertEqual(m.state, "on.playing.fast")
        self.assertEqual(log, ["-on.paused", "-on", "+on", "+on.playing", "+on.playing.fast"])

    def test_child_to_parent_is_external(self):
        extra = [Transition("on.paused", "up", "on")]
        m, log = build(extra, initial="on.paused")
        del log[:]
        m.send("up")
        self.assertEqual(m.state, "on.stopped")
        self.assertEqual(log, ["-on.paused", "-on", "+on", "+on.stopped"])

    def test_deep_to_cousin(self):
        extra = [Transition("on.playing.fast", "cousin", "on.stopped")]
        m, log = build(extra, initial="on.playing.fast")
        del log[:]
        m.send("cousin")
        self.assertEqual(log, ["-on.playing.fast", "-on.playing", "+on.stopped"])

    def test_two_top_level_trees(self):
        states = ["a", "a.x", "b", "b.y", "b.z"]
        init = {"a": "a.x", "b": "b.y"}
        log = []
        ts = [Transition("a.x", "go", "b.z")]
        m = Machine(states, ts, "a", initials=init,
                    on_exit={"a": lambda p: log.append("-a"), "a.x": lambda p: log.append("-a.x")},
                    on_enter={"b": lambda p: log.append("+b"), "b.z": lambda p: log.append("+b.z")})
        m.send("go")
        self.assertEqual(log, ["-a.x", "-a", "+b", "+b.z"])
        self.assertEqual(m.configuration(), ["b", "b.z"])


class Internal(unittest.TestCase):
    def test_internal_on_leaf(self):
        extra = [Transition("on.paused", "ping", None, action=lambda p: None)]
        calls = []
        extra = [Transition("on.paused", "ping", None, action=lambda p: calls.append(1))]
        m, log = build(extra, initial="on.paused")
        del log[:]
        self.assertTrue(m.send("ping"))
        self.assertEqual((calls, log, m.state), ([1], [], "on.paused"))

    def test_internal_on_ancestor(self):
        calls = []
        extra = [Transition("on", "ping", None, action=lambda p: calls.append(p))]
        m, log = build(extra, initial="on.playing")
        del log[:]
        self.assertTrue(m.send("ping", a=2))
        self.assertEqual((calls, log, m.state), ([{"a": 2}], [], "on.playing.normal"))

    def test_internal_guard_failure_falls_through(self):
        calls = []
        extra = [Transition("on.stopped", "q", None, guard=lambda p: False, action=lambda p: calls.append("inner")),
                 Transition("on", "q", None, action=lambda p: calls.append("outer"))]
        m, _ = build(extra, initial="on")
        m.send("q")
        self.assertEqual(calls, ["outer"])

    def test_multiple_sequential_transitions(self):
        m, log = build()
        for ev in ("power", "play", "ff", "pause", "play", "power"):
            self.assertTrue(m.send(ev), ev)
        self.assertEqual(m.state, "off")
        self.assertEqual(log[-5:], ["-on.playing.normal", "-on.playing", "-on", "act:off", "+off"])


if __name__ == "__main__":
    unittest.main()
