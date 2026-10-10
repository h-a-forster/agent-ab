import unittest

from hsm import Machine, Transition


class Flat(unittest.TestCase):
    def make(self, log):
        return Machine(
            ["idle", "running"],
            [
                Transition("idle", "start", "running", action=lambda p: log.append("act")),
                Transition("running", "stop", "idle", guard=lambda p: p.get("ok", True)),
                Transition("running", "tick", None, action=lambda p: log.append("tick")),
                Transition("running", "again", "running"),
            ],
            "idle",
            on_enter={"idle": lambda p: log.append("+idle"), "running": lambda p: log.append("+running")},
            on_exit={"idle": lambda p: log.append("-idle"), "running": lambda p: log.append("-running")},
        )

    def test_flow(self):
        log = []
        m = self.make(log)
        self.assertEqual(log, ["+idle"])
        self.assertTrue(m.send("start"))
        self.assertEqual(m.state, "running")
        self.assertEqual(log, ["+idle", "-idle", "act", "+running"])

    def test_guard_and_ignored(self):
        m = self.make([])
        self.assertFalse(m.send("stop"))
        m.send("start")
        self.assertFalse(m.send("stop", ok=False))
        self.assertEqual(m.state, "running")
        self.assertTrue(m.send("stop"))

    def test_internal_and_self(self):
        log = []
        m = self.make(log)
        m.send("start")
        del log[:]
        m.send("tick")
        self.assertEqual(log, ["tick"])
        del log[:]
        m.send("again")
        self.assertEqual(log, ["-running", "+running"])

    def test_unknown_state(self):
        with self.assertRaises(ValueError):
            Machine(["a"], [Transition("a", "e", "zzz")], "a")


if __name__ == "__main__":
    unittest.main()
