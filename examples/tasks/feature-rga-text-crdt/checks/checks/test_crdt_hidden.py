import json
import random
import time
import unittest
from collections import defaultdict

from crdtext import Document, Op, Replica, Session


# ---------------------------------------------------------------- reference model

def closure(received):
    """Operations that can be applied given the received ones (causal readiness fixpoint)."""
    inserts = {o.id: o for o in received if o.kind == "ins"}
    deletes = {o.ref for o in received if o.kind == "del"}
    have = set()
    changed = True
    while changed:
        changed = False
        for ident, o in inserts.items():
            if ident not in have and (o.ref is None or o.ref in have):
                have.add(ident)
                changed = True
    applied_deletes = {t for t in deletes if t in have}
    return have, applied_deletes, inserts


def model_state(received):
    have, dead, inserts = closure(received)
    children = defaultdict(list)
    for ident in have:
        children[inserts[ident].ref].append(ident)
    for lst in children.values():
        lst.sort(reverse=True)
    order = []
    stack = list(reversed(children[None]))
    while stack:
        ident = stack.pop()
        order.append(ident)
        stack.extend(reversed(children[ident]))
    vis = [i for i in order if i not in dead]
    text = "".join(inserts[i].char for i in vis)
    return text, vis, have, dead


def applied_count(received):
    have, dead, _ = closure(received)
    return len(have) + len(dead)


def pending_count(received):
    have, dead, inserts = closure(received)
    keys = set()
    for o in received:
        if o.kind == "ins" and o.id not in have:
            keys.add(("i", o.id))
        elif o.kind == "del" and o.ref not in have:
            keys.add(("d", o.ref))
    return len(keys)


def expected_local(received, rid, kind, index, char=None):
    text, vis, have, dead = model_state(received)
    if kind == "ins":
        counter = 1 + max([i[0] for i in have], default=0)
        return Op("ins", (counter, rid), vis[index - 1] if index > 0 else None, char)
    return Op("del", None, vis[index], None)


class Simulation(unittest.TestCase):
    def run_sim(self, seed, nrep, steps, p_local=0.5, p_delete=0.3, p_dup=0.15, alphabet="abcxyz"):
        rng = random.Random(seed)
        rids = ["R%d" % i for i in range(nrep)] if seed % 2 else [chr(ord("A") + i) for i in range(nrep)]
        reps = {r: Replica(r) for r in rids}
        received = {r: [] for r in rids}          # every op delivered to the replica (with dups)
        inflight = {r: [] for r in rids}
        sent = {r: [] for r in rids}               # ops already delivered once to r
        everything = []
        for step in range(steps):
            r = rng.choice(rids)
            rep = reps[r]
            if rng.random() < p_local:
                text, vis, _, _ = model_state(received[r])
                if vis and rng.random() < p_delete:
                    idx = rng.randrange(len(vis))
                    want = expected_local(received[r], r, "del", idx)
                    got = rep.delete(idx)
                else:
                    idx = rng.randrange(len(vis) + 1)
                    ch = rng.choice(alphabet)
                    want = expected_local(received[r], r, "ins", idx, ch)
                    got = rep.insert(idx, ch)
                self.assertEqual(got, want, (seed, step))
                received[r].append(got)
                everything.append(got)
                for o in rids:
                    if o != r:
                        inflight[o].append(got)
            else:
                batch = []
                if inflight[r]:
                    k = rng.randrange(1, len(inflight[r]) + 1)
                    rng.shuffle(inflight[r])
                    batch = inflight[r][:k]
                    inflight[r] = inflight[r][k:]
                if sent[r] and rng.random() < p_dup:
                    batch += rng.sample(sent[r], min(len(sent[r]), rng.randrange(1, 4)))
                rng.shuffle(batch)
                for op in batch:
                    before = applied_count(received[r])
                    received[r].append(op)
                    n = rep.apply(op)
                    self.assertEqual(n, applied_count(received[r]) - before, (seed, step, op))
                    sent[r].append(op)
            text, vis, _, _ = model_state(received[r])
            self.assertEqual(rep.text(), text, (seed, step))
            self.assertEqual(len(rep), len(text))
            self.assertEqual(rep.visible_ids(), vis)
            self.assertEqual(rep.pending(), pending_count(received[r]), (seed, step))
        # deliver everything, in different orders, with duplicates
        final = model_state(everything)[0]
        for r in rids:
            ops = list(everything) + rng.sample(everything, min(len(everything), 5))
            rng.shuffle(ops)
            for op in ops:
                reps[r].apply(op)
            self.assertEqual(reps[r].text(), final, (seed, r))
            self.assertEqual(reps[r].pending(), 0)
            self.assertEqual(reps[r].visible_ids(), model_state(everything)[1])
        return reps, everything

    def test_history_replays_to_same_state(self):
        for seed in range(600, 606):
            reps, everything = self.run_sim(seed, 3, 120)
            for r, rep in reps.items():
                fresh = Replica("Z")
                seen_ids = set()
                for op in rep.history():
                    # causal order: a dependency is always applied first
                    if op.kind == "ins":
                        self.assertTrue(op.ref is None or op.ref in seen_ids)
                        seen_ids.add(op.id)
                    else:
                        self.assertIn(op.ref, seen_ids)
                    self.assertEqual(fresh.apply(op), 1)
                self.assertEqual(fresh.text(), rep.text())
                self.assertEqual(fresh.pending(), 0)
                self.assertEqual(len(rep.history()), len(set(map(lambda o: (o.kind, o.id, o.ref), rep.history()))))


def _add_sim_tests():
    plans = [
        ("two", range(100, 120), dict(nrep=2, steps=120)),
        ("three", range(200, 215), dict(nrep=3, steps=160)),
        ("five_mostly_local", range(300, 306), dict(nrep=5, steps=220, p_local=0.7)),
        ("mostly_syncing", range(400, 410), dict(nrep=3, steps=150, p_local=0.3)),
        ("small_alphabet_deletes", range(500, 510), dict(nrep=3, steps=150, p_delete=0.5, alphabet="ab")),
    ]

    def mk(seed, kw):
        def t(self):
            self.run_sim(seed, **kw)
        return t

    for name, seeds, kw in plans:
        for seed in seeds:
            setattr(Simulation, "test_%s_seed_%d" % (name, seed), mk(seed, kw))


_add_sim_tests()


class Basics(unittest.TestCase):
    def test_ops(self):
        a = Op("ins", (1, "A"), None, "x")
        self.assertEqual(a, Op("ins", (1, "A"), None, "x"))
        self.assertEqual(hash(a), hash(Op("ins", (1, "A"), None, "x")))
        self.assertNotEqual(a, Op("ins", (1, "A"), None, "y"))
        d = Op("del", None, (1, "A"), None)
        self.assertEqual((d.kind, d.id, d.ref, d.char), ("del", None, (1, "A"), None))
        with self.assertRaises(Exception):
            a.char = "z"
        for op in (a, d, Op("ins", (7, "B"), (1, "A"), "é")):
            wire = json.loads(json.dumps(op.to_dict()))
            self.assertEqual(Op.from_dict(wire), op)
        self.assertEqual(a.to_dict(), {"kind": "ins", "id": [1, "A"], "ref": None, "char": "x"})
        self.assertEqual(d.to_dict(), {"kind": "del", "ref": [1, "A"]})

    def test_single_replica(self):
        r = Replica("A")
        self.assertEqual((r.text(), len(r), r.pending(), r.history(), r.visible_ids()), ("", 0, 0, [], []))
        ops = r.insert_text(0, "hello")
        self.assertEqual([o.id for o in ops], [(i, "A") for i in range(1, 6)])
        self.assertEqual([o.ref for o in ops], [None] + [(i, "A") for i in range(1, 5)])
        r.insert(5, "!")
        r.insert(0, ">")
        self.assertEqual(r.text(), ">hello!")
        d = r.delete(1)
        self.assertEqual(d, Op("del", None, (1, "A"), None))
        self.assertEqual(r.text(), ">ello!")
        r.insert(1, "H")
        self.assertEqual(r.text(), ">Hello!")
        self.assertEqual(r.visible_ids()[1], (8, "A"))
        self.assertEqual(len(r.history()), 9)

    def test_insert_after_deleted_neighbour(self):
        r = Replica("A")
        r.insert_text(0, "abc")
        r.delete(1)
        op = r.insert(1, "X")
        self.assertEqual(op.ref, (1, "A"))
        self.assertEqual(r.text(), "aXc")

    def test_errors(self):
        for bad in ("", None, 5, b"A"):
            with self.assertRaises(ValueError):
                Replica(bad)
        r = Replica("A")
        r.insert_text(0, "ab")
        for fn in (lambda: r.insert(3, "x"), lambda: r.insert(-1, "x"), lambda: r.delete(2), lambda: r.delete(-1)):
            with self.assertRaises(IndexError):
                fn()
        for ch in ("", "xy", 5, None):
            with self.assertRaises(ValueError):
                r.insert(0, ch)
        with self.assertRaises(ValueError):
            r.apply(Op("move", (1, "B"), None, "x"))
        self.assertEqual(r.text(), "ab")
        self.assertEqual(r.insert_text(1, ""), [])

    def test_concurrent_inserts_at_same_place(self):
        a, b = Replica("A"), Replica("B")
        for op in a.insert_text(0, "abc"):
            b.apply(op)
        x = a.insert(1, "X")
        y = b.insert(1, "Y")
        self.assertEqual(x.id[0], y.id[0])
        self.assertEqual(a.apply(y), 1)
        self.assertEqual(b.apply(x), 1)
        self.assertEqual((a.text(), b.text()), ("aYXbc", "aYXbc"))   # (4, "B") > (4, "A") comes first

    def test_no_interleaving_of_concurrent_runs(self):
        a, b = Replica("A"), Replica("B")
        oa = a.insert_text(0, "abc")
        ob = b.insert_text(0, "xyz")
        for o in ob:
            a.apply(o)
        for o in oa:
            b.apply(o)
        self.assertEqual((a.text(), b.text()), ("xyzabc", "xyzabc"))
        c = Replica("C")
        for o in oa + ob:
            c.apply(o)
        self.assertEqual(c.text(), "xyzabc")

    def test_concurrent_runs_in_middle_and_nested(self):
        a, b = Replica("A"), Replica("B")
        base = a.insert_text(0, "[]")
        for o in base:
            b.apply(o)
        oa = a.insert_text(1, "aa")
        ob = b.insert_text(1, "bb")
        oa2 = a.insert_text(2, "!")        # inside A's own run
        for o in ob:
            a.apply(o)
        for o in oa + oa2:
            b.apply(o)
        self.assertEqual(a.text(), b.text())
        self.assertEqual(a.text(), "[bba!a]")

    def test_causal_buffering(self):
        a = Replica("A")
        ops = a.insert_text(0, "abc")
        d = a.delete(1)
        b = Replica("B")
        self.assertEqual(b.apply(d), 0)
        self.assertEqual(b.pending(), 1)
        self.assertEqual(b.apply(ops[2]), 0)
        self.assertEqual(b.apply(ops[2]), 0)           # duplicate of a buffered op
        self.assertEqual(b.pending(), 2)
        self.assertEqual(b.apply(ops[1]), 0)
        self.assertEqual(b.pending(), 3)
        self.assertEqual(b.text(), "")
        self.assertEqual(b.apply(ops[0]), 4)           # releases everything
        self.assertEqual((b.text(), b.pending()), ("ac", 0))
        self.assertEqual(b.apply(d), 0)
        self.assertEqual(b.apply(ops[0]), 0)
        self.assertEqual(len(b.history()), 4)

    def test_delete_is_idempotent_and_commutes(self):
        a, b = Replica("A"), Replica("B")
        ops = a.insert_text(0, "abc")
        for o in ops:
            b.apply(o)
        da = a.delete(1)
        db = b.delete(1)
        self.assertEqual(da, db)
        self.assertEqual(a.apply(db), 0)
        self.assertEqual(b.apply(da), 0)
        self.assertEqual((a.text(), b.text()), ("ac", "ac"))

    def test_insert_after_concurrently_deleted_char(self):
        a, b = Replica("A"), Replica("B")
        for o in a.insert_text(0, "ab"):
            b.apply(o)
        d = a.delete(0)
        i = b.insert(1, "X")             # after "a"
        a.apply(i)
        b.apply(d)
        self.assertEqual((a.text(), b.text()), ("Xb", "Xb"))

    def test_lamport_clock(self):
        a = Replica("A")
        far = Op("ins", (10, "B"), None, "z")
        a.apply(far)
        self.assertEqual(a.insert(1, "q").id, (11, "A"))
        late = Op("ins", (3, "C"), (99, "C"), "p")       # not applicable: must not move the clock
        a.apply(late)
        self.assertEqual(a.insert(0, "r").id, (12, "A"))
        a.apply(Op("ins", (50, "C"), (99, "C"), "s"))     # buffered too
        self.assertEqual(a.insert(0, "t").id, (13, "A"))
        a.apply(Op("ins", (99, "C"), None, "u"))          # releases both buffered inserts
        self.assertEqual(a.pending(), 0)
        self.assertEqual(a.insert(0, "v").id, (100, "A"))

    def test_replica_id_breaks_ties(self):
        c = Replica("C")
        x = Op("ins", (1, "B"), None, "b")
        y = Op("ins", (1, "A"), None, "a")
        z = Op("ins", (1, "a"), None, "l")
        for op in (x, y, z):
            c.apply(op)
        self.assertEqual(c.text(), "lba")     # (1,'a') > (1,'B') > (1,'A') as plain tuple comparison

    def test_old_api_still_there(self):
        d = Document("hello")
        d.insert(5, " world")
        d.delete(0, 6)
        self.assertEqual(d.text(), "world")
        s = Session("ab")
        self.assertEqual(s.edit("alice", "ins", 1, "X"), "aXb")
        self.assertEqual(s.edit("bob", "del", 0, 2), "b")


class Performance(unittest.TestCase):
    def test_many_operations(self):
        rng = random.Random(7)
        a = Replica("A")
        ops = []
        t = time.perf_counter()
        for i in range(15000):
            n = len(a)
            if n and rng.random() < 0.25:
                ops.append(a.delete(rng.randrange(n)))
            else:
                ops.append(a.insert(rng.randrange(n + 1), rng.choice("abcdef")))
        self.assertLess(time.perf_counter() - t, 5.0)
        text = a.text()
        self.assertEqual(len(a), len(text))
        shuffled = list(ops)
        rng.shuffle(shuffled)
        b = Replica("B")
        t = time.perf_counter()
        for op in shuffled:
            b.apply(op)
        self.assertLess(time.perf_counter() - t, 5.0)
        self.assertEqual((b.text(), b.pending()), (text, 0))
        c = Replica("C")
        t = time.perf_counter()
        for op in reversed(ops):
            c.apply(op)
        self.assertLess(time.perf_counter() - t, 5.0)
        self.assertEqual((c.text(), c.pending()), (text, 0))

    def test_typing_runs_at_one_place(self):
        a = Replica("A")
        t = time.perf_counter()
        ops = a.insert_text(0, "x" * 20000)
        ops += [a.insert(10000, "y") for _ in range(2000)]
        self.assertLess(time.perf_counter() - t, 5.0)
        b = Replica("B")
        for op in ops:
            b.apply(op)
        self.assertEqual(a.text(), b.text())
        self.assertEqual(len(a), 22000)


if __name__ == "__main__":
    unittest.main()
