import unittest

from ttlstore import Stats, TTLCache
from ttlstore.clock import ManualClock


class Basics(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()
        self.cache = TTLCache(2, 10, clock=self.clock)

    def test_expiry(self):
        self.cache.set("a", 1)
        self.clock.advance(9)
        self.assertEqual(self.cache.get("a"), 1)
        self.clock.advance(1)
        self.assertIsNone(self.cache.get("a"))
        self.assertEqual(self.cache.stats(), Stats(hits=1, misses=1, evictions=0, expirations=1))

    def test_lru_eviction(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.get("a")
        self.cache.set("c", 3)
        self.assertEqual(self.cache.keys(), ["a", "c"])
        self.assertEqual(self.cache.stats().evictions, 1)

    def test_overwrite_does_not_evict(self):
        self.cache.set("a", 1)
        self.cache.set("b", 2)
        self.cache.set("a", 3)
        self.assertEqual(len(self.cache), 2)
        self.assertEqual(self.cache.get("a"), 3)

    def test_delete(self):
        self.cache.set("a", 1)
        self.assertTrue(self.cache.delete("a"))
        self.assertFalse(self.cache.delete("a"))

    def test_validation(self):
        with self.assertRaises(ValueError):
            TTLCache(0, 1)
        with self.assertRaises(ValueError):
            TTLCache(1, 0)


if __name__ == "__main__":
    unittest.main()
