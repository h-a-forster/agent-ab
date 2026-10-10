import math
import unittest

from ttlstore import Stats, TTLCache


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


def make(capacity=3, ttl=10, **kw):
    clock = Clock()
    return TTLCache(capacity, ttl, clock=clock, **kw), clock


class PerEntryTtl(unittest.TestCase):
    def test_override(self):
        c, clk = make()
        c.set("a", 1, ttl=3)
        c.set("b", 2)
        clk.advance(3)
        self.assertNotIn("a", c)
        self.assertIn("b", c)

    def test_boundary_inclusive(self):
        c, clk = make()
        c.set("a", 1, ttl=5)
        clk.advance(4.999)
        self.assertEqual(c.get("a"), 1)
        clk.advance(0.001)
        self.assertIsNone(c.get("a"))

    def test_infinite(self):
        c, clk = make()
        c.set("a", 1, ttl=math.inf)
        clk.advance(1e12)
        self.assertEqual(c.get("a"), 1)
        self.assertEqual(c.ttl_remaining("a"), math.inf)
        self.assertEqual(TTLCache(1, math.inf, clock=clk).ttl, math.inf)

    def test_invalid_ttl(self):
        c, _ = make()
        for bad in (0, -1, "5", []):
            with self.assertRaises(ValueError):
                c.set("a", 1, ttl=bad)
        with self.assertRaises(ValueError):
            TTLCache(2, -3)
        with self.assertRaises(ValueError):
            TTLCache(2, "10")
        self.assertEqual(len(c), 0)

    def test_replace_resets_everything(self):
        c, clk = make()
        c.set("a", 1, ttl=2, tags=["x"])
        clk.advance(1)
        c.set("a", 2)
        self.assertEqual(c.ttl_remaining("a"), 10)
        self.assertEqual(c.invalidate_tag("x"), 0)
        self.assertEqual(c.get("a"), 2)


class Sliding(unittest.TestCase):
    def test_get_extends(self):
        c, clk = make(sliding=True)
        c.set("a", 1)
        for _ in range(5):
            clk.advance(8)
            self.assertEqual(c.get("a"), 1)
        clk.advance(10)
        self.assertIsNone(c.get("a"))

    def test_uses_entry_ttl(self):
        c, clk = make(sliding=True)
        c.set("a", 1, ttl=4)
        clk.advance(3)
        c.get("a")
        clk.advance(3)
        self.assertEqual(c.get("a"), 1)
        clk.advance(4)
        self.assertIsNone(c.get("a"))

    def test_peek_and_contains_do_not_extend(self):
        c, clk = make(sliding=True)
        c.set("a", 1)
        clk.advance(6)
        c.peek("a")
        "a" in c
        c.ttl_remaining("a")
        clk.advance(4)
        self.assertNotIn("a", c)

    def test_non_sliding_default(self):
        c, clk = make()
        c.set("a", 1)
        clk.advance(6)
        c.get("a")
        clk.advance(4)
        self.assertIsNone(c.get("a"))

    def test_miss_does_not_create_or_extend(self):
        c, clk = make(sliding=True)
        self.assertIsNone(c.get("zzz"))
        self.assertEqual(len(c), 0)


class ReadOnlyQueries(unittest.TestCase):
    def test_len_counts_live_only_without_mutation(self):
        c, clk = make()
        c.set("a", 1, ttl=1)
        c.set("b", 2)
        clk.advance(2)
        self.assertEqual(len(c), 1)
        self.assertEqual(c.keys(), ["b"])
        self.assertNotIn("a", c)
        self.assertEqual(c.stats(), Stats())
        self.assertEqual(c.peek("a", "dflt"), "dflt")
        self.assertIsNone(c.ttl_remaining("a"))
        self.assertEqual(c.stats().expirations, 0)

    def test_keys_order_and_recency_untouched(self):
        c, clk = make()
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        c.get("a")
        self.assertEqual(c.keys(), ["b", "c", "a"])
        c.peek("b")
        "b" in c
        len(c)
        self.assertEqual(c.keys(), ["b", "c", "a"])
        c.set("d", 4)
        self.assertEqual(c.keys(), ["c", "a", "d"])

    def test_peek_and_ttl_remaining(self):
        c, clk = make()
        c.set("a", 1, ttl=7)
        clk.advance(2.5)
        self.assertEqual(c.peek("a"), 1)
        self.assertEqual(c.ttl_remaining("a"), 4.5)
        self.assertEqual(c.stats().hits, 0)
        self.assertIsNone(c.ttl_remaining("nope"))
        self.assertEqual(c.peek("nope", 9), 9)


class SetAndEviction(unittest.TestCase):
    def test_set_purges_expired_before_evicting(self):
        c, clk = make(capacity=2)
        c.set("a", 1, ttl=1)
        c.set("b", 2)
        clk.advance(2)
        c.set("c", 3)
        self.assertEqual(c.keys(), ["b", "c"])
        self.assertEqual(c.stats(), Stats(expirations=1))

    def test_evicts_lru_when_all_live(self):
        c, _ = make(capacity=2)
        c.set("a", 1)
        c.set("b", 2)
        c.get("a")
        c.set("c", 3)
        self.assertEqual(c.keys(), ["a", "c"])
        self.assertEqual(c.stats().evictions, 1)

    def test_replace_never_evicts(self):
        c, _ = make(capacity=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("b", 3)
        self.assertEqual(c.stats().evictions, 0)
        self.assertEqual(c.keys(), ["a", "b"])

    def test_replacing_expired_key_counts_expiration_not_eviction(self):
        c, clk = make(capacity=1)
        c.set("a", 1, ttl=1)
        clk.advance(1)
        c.set("a", 2)
        self.assertEqual(c.stats(), Stats(expirations=1))
        self.assertEqual(c.get("a"), 2)

    def test_expired_entries_removed_even_when_not_full(self):
        c, clk = make(capacity=5)
        c.set("a", 1, ttl=1)
        c.set("b", 1, ttl=1)
        clk.advance(1)
        c.set("c", 1)
        self.assertEqual(c.stats().expirations, 2)

    def test_capacity_never_exceeded_over_many_sets(self):
        c, clk = make(capacity=3, ttl=5)
        for i in range(50):
            c.set(i, i)
            clk.advance(1)
            self.assertLessEqual(len(c), 3)
        st = c.stats()
        self.assertEqual(st.evictions + st.expirations, 50 - len(c))


class GetStats(unittest.TestCase):
    def test_expired_get_is_miss_and_expiration_once(self):
        c, clk = make()
        c.set("a", 1)
        clk.advance(10)
        self.assertEqual(c.get("a", "d"), "d")
        self.assertIsNone(c.get("a"))
        self.assertEqual(c.stats(), Stats(hits=0, misses=2, expirations=1))

    def test_hit_and_miss(self):
        c, _ = make()
        c.set("a", 1)
        c.get("a")
        c.get("b")
        self.assertEqual(c.stats(), Stats(hits=1, misses=1))


class Touch(unittest.TestCase):
    def test_touch_restarts_expiry(self):
        c, clk = make()
        c.set("a", 1)
        clk.advance(8)
        self.assertTrue(c.touch("a"))
        clk.advance(8)
        self.assertEqual(c.peek("a"), 1)
        self.assertEqual(c.stats(), Stats())

    def test_touch_with_new_ttl_sticks(self):
        c, clk = make(sliding=True)
        c.set("a", 1)
        self.assertTrue(c.touch("a", ttl=3))
        clk.advance(2)
        c.get("a")
        clk.advance(2)
        self.assertEqual(c.get("a"), 1)
        clk.advance(3)
        self.assertIsNone(c.get("a"))

    def test_touch_keeps_recency(self):
        c, _ = make()
        c.set("a", 1)
        c.set("b", 2)
        c.touch("a")
        self.assertEqual(c.keys(), ["a", "b"])

    def test_touch_missing_and_expired(self):
        c, clk = make()
        self.assertFalse(c.touch("x"))
        c.set("a", 1)
        clk.advance(10)
        self.assertFalse(c.touch("a"))
        self.assertEqual(c.stats(), Stats(expirations=1))
        self.assertNotIn("a", c)

    def test_touch_invalid_ttl(self):
        c, _ = make()
        c.set("a", 1)
        with self.assertRaises(ValueError):
            c.touch("a", ttl=0)


class DeleteAndPurge(unittest.TestCase):
    def test_delete_live(self):
        c, _ = make()
        c.set("a", 1)
        self.assertTrue(c.delete("a"))
        self.assertFalse(c.delete("a"))
        self.assertEqual(c.stats(), Stats())

    def test_delete_expired(self):
        c, clk = make()
        c.set("a", 1)
        clk.advance(10)
        self.assertFalse(c.delete("a"))
        self.assertEqual(c.stats().expirations, 1)
        self.assertFalse(c.delete("a"))
        self.assertEqual(c.stats().expirations, 1)

    def test_purge(self):
        c, clk = make()
        c.set("a", 1, ttl=1)
        c.set("b", 2, ttl=2)
        c.set("c", 3)
        clk.advance(2)
        self.assertEqual(c.purge(), 2)
        self.assertEqual(c.purge(), 0)
        self.assertEqual(c.keys(), ["c"])
        self.assertEqual(c.stats().expirations, 2)


class Tags(unittest.TestCase):
    def test_invalidate(self):
        c, _ = make(capacity=10)
        c.set("a", 1, tags=["user:1", "price"])
        c.set("b", 2, tags=["user:2", "price"])
        c.set("c", 3, tags=("user:1",))
        c.set("d", 4)
        self.assertEqual(c.invalidate_tag("price"), 2)
        self.assertEqual(c.keys(), ["c", "d"])
        self.assertEqual(c.invalidate_tag("price"), 0)
        self.assertEqual(c.invalidate_tag("user:1"), 1)
        self.assertEqual(c.stats().invalidations, 3)

    def test_expired_tagged_counted_as_expirations(self):
        c, clk = make(capacity=10)
        c.set("a", 1, ttl=1, tags=["t"])
        c.set("b", 2, tags=["t"])
        clk.advance(1)
        self.assertEqual(c.invalidate_tag("t"), 1)
        st = c.stats()
        self.assertEqual((st.invalidations, st.expirations), (1, 1))
        self.assertEqual(c.keys(), [])

    def test_does_not_purge_unrelated_expired(self):
        c, clk = make(capacity=10)
        c.set("a", 1, ttl=1)
        c.set("b", 2, tags=["t"])
        clk.advance(1)
        c.invalidate_tag("t")
        self.assertEqual(c.stats().expirations, 0)
        self.assertEqual(c.purge(), 1)

    def test_unknown_tag_and_generator_tags(self):
        c, _ = make()
        self.assertEqual(c.invalidate_tag("none"), 0)
        c.set("a", 1, tags=(t for t in ["x", "y"]))
        self.assertEqual(c.invalidate_tag("y"), 1)

    def test_stats_fields(self):
        self.assertEqual(Stats(1, 2, 3, 4, 5).invalidations, 5)
        self.assertEqual(Stats().invalidations, 0)


if __name__ == "__main__":
    unittest.main()
