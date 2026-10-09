import unittest

from keepcache import LRUCache


class LRUBasics(unittest.TestCase):
    def test_capacity_validation(self):
        for bad in (0, -1, 1.5):
            with self.assertRaises(ValueError):
                LRUCache(bad)

    def test_put_get(self):
        cache = LRUCache(3)
        cache.put("a", 1)
        self.assertEqual(cache.get("a"), 1)
        self.assertIsNone(cache.get("missing"))
        self.assertEqual(cache.get("missing", 0), 0)
        self.assertIn("a", cache)
        self.assertEqual(len(cache), 1)

    def test_oldest_inserted_is_evicted(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        self.assertNotIn("a", cache)
        self.assertEqual(len(cache), 2)

    def test_get_or_compute_caches(self):
        cache = LRUCache(2)
        self.assertEqual(cache.get_or_compute("x", lambda k: k * 2), "xx")
        self.assertEqual(cache.peek("x"), "xx")


if __name__ == "__main__":
    unittest.main()
