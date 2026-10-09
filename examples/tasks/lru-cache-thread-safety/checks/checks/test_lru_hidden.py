import random
import threading
import time
import unittest

from keepcache import LRUCache

JOIN_TIMEOUT = 20.0


def run_threads(targets):
    """Start every target in a daemon thread; return True if all finished in time."""
    threads = [threading.Thread(target=t, daemon=True) for t in targets]
    for t in threads:
        t.start()
    deadline = time.monotonic() + JOIN_TIMEOUT
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return not any(t.is_alive() for t in threads)


class Recency(unittest.TestCase):
    def test_get_marks_recently_used(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)
        cache.put("c", 3)
        self.assertIn("a", cache)
        self.assertNotIn("b", cache)
        self.assertIn("c", cache)

    def test_peek_and_contains_do_not_touch_recency(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.peek("a"), 1)
        self.assertTrue("a" in cache)
        cache.put("c", 3)
        self.assertNotIn("a", cache)
        self.assertEqual(cache.stats().hits, 0)
        self.assertEqual(cache.stats().misses, 0)

    def test_get_or_compute_hit_marks_recently_used(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get_or_compute("a", lambda k: 99), 1)
        cache.put("c", 3)
        self.assertEqual(sorted(k for k in "abc" if k in cache), ["a", "c"])

    def test_long_sequence_matches_reference_model(self):
        rng = random.Random(1234)
        cache = LRUCache(5)
        model = []  # keys, oldest first
        values = {}
        for step in range(3000):
            key = rng.randrange(12)
            if rng.random() < 0.5:
                cache.put(key, step)
                values[key] = step
                if key in model:
                    model.remove(key)
                model.append(key)
                if len(model) > 5:
                    values.pop(model.pop(0))
            else:
                got = cache.get(key, "missing")
                if key in model:
                    self.assertEqual(got, values[key])
                    model.remove(key)
                    model.append(key)
                else:
                    self.assertEqual(got, "missing")
            self.assertEqual(len(cache), len(model))
        for key in range(12):
            self.assertEqual(key in cache, key in model)


class Replacement(unittest.TestCase):
    def test_reput_replaces_without_evicting(self):
        evicted = []
        cache = LRUCache(3, on_evict=lambda k, v: evicted.append((k, v)))
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.put("a", 10)
        cache.put("a", 11)
        self.assertEqual(len(cache), 3)
        self.assertEqual(evicted, [])
        self.assertEqual(cache.peek("a"), 11)
        self.assertEqual(cache.stats().evictions, 0)
        cache.put("d", 4)  # "b" is now the least recently used
        self.assertEqual(evicted, [("b", 2)])
        cache.put("e", 5)
        cache.put("f", 6)
        self.assertEqual(evicted, [("b", 2), ("c", 3), ("a", 11)])
        self.assertEqual(cache.stats().evictions, 3)

    def test_capacity_one(self):
        cache = LRUCache(1)
        for i in range(10):
            cache.put("k", i)
            self.assertEqual(len(cache), 1)
        cache.put("other", 0)
        self.assertEqual(len(cache), 1)
        self.assertNotIn("k", cache)
        self.assertEqual(cache.stats().evictions, 1)

    def test_clear_has_no_callbacks(self):
        evicted = []
        cache = LRUCache(2, on_evict=lambda k, v: evicted.append(k))
        cache.put(1, 1)
        cache.put(2, 2)
        cache.clear()
        self.assertEqual(len(cache), 0)
        cache.put(3, 3)
        cache.put(4, 4)
        self.assertEqual(evicted, [])


class Stats(unittest.TestCase):
    def test_hits_and_misses(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.get("a")
        cache.get("a")
        cache.get("zz")
        cache.get("a", None)
        s = cache.stats()
        self.assertEqual((s.hits, s.misses, s.evictions), (3, 1, 0))


class Callbacks(unittest.TestCase):
    def test_callback_can_use_cache(self):
        seen = []
        holder = {}

        def on_evict(key, value):
            c = holder["cache"]
            seen.append((key, value, len(c), c.peek("x"), key in c))
            c.get("x")

        cache = LRUCache(2, on_evict=on_evict)
        holder["cache"] = cache

        def work():
            cache.put("x", 1)
            cache.put("y", 2)
            cache.get("x")
            cache.put("z", 3)

        self.assertTrue(run_threads([work]), "deadlock when on_evict uses the cache")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][:2], ("y", 2))
        self.assertFalse(seen[0][4])


class ComputeOnce(unittest.TestCase):
    def test_concurrent_misses_compute_once(self):
        cache = LRUCache(10)
        calls = []
        calls_lock = threading.Lock()
        start = threading.Barrier(16)
        results = []

        def compute(key):
            with calls_lock:
                calls.append(key)
            time.sleep(0.3)
            return f"value-{key}"

        def worker():
            start.wait()
            results.append(cache.get_or_compute("k", compute))

        self.assertTrue(run_threads([worker] * 16), "threads did not finish")
        self.assertEqual(calls, ["k"])
        self.assertEqual(results, ["value-k"] * 16)
        self.assertEqual(cache.peek("k"), "value-k")

    def test_compute_failure_propagates_and_is_retried(self):
        cache = LRUCache(2)
        attempts = []

        def flaky(key):
            attempts.append(key)
            if len(attempts) == 1:
                raise RuntimeError("backend down")
            return 42

        with self.assertRaises(RuntimeError):
            cache.get_or_compute("k", flaky)
        self.assertNotIn("k", cache)
        self.assertEqual(cache.get_or_compute("k", flaky), 42)
        self.assertEqual(attempts, ["k", "k"])

    def test_slow_compute_does_not_block_other_keys(self):
        cache = LRUCache(4)
        cache.put("ready", "yes")
        release = threading.Event()
        entered = threading.Event()
        timings = {}

        def slow(key):
            entered.set()
            release.wait(10)
            return "slow"

        def computing():
            cache.get_or_compute("slow-key", slow)

        def reader():
            entered.wait(10)
            t0 = time.monotonic()
            timings["get"] = cache.get("ready")
            timings["put"] = cache.put("other", 1)
            timings["len"] = len(cache)
            timings["elapsed"] = time.monotonic() - t0
            release.set()

        self.assertTrue(run_threads([computing, reader]))
        self.assertEqual(timings["get"], "yes")
        self.assertLess(timings["elapsed"], 2.0)
        self.assertEqual(cache.peek("slow-key"), "slow")


class Stress(unittest.TestCase):
    def test_many_threads_keep_invariants(self):
        capacity = 32
        evictions = []
        ev_lock = threading.Lock()

        def on_evict(k, v):
            with ev_lock:
                evictions.append(k)

        cache = LRUCache(capacity, on_evict=on_evict)
        errors = []
        gets_done = []
        computes_done = []
        oversize = []

        def worker(seed):
            rng = random.Random(seed)
            gets = computes = 0
            try:
                for _ in range(4000):
                    key = rng.randrange(100)
                    op = rng.random()
                    if op < 0.45:
                        cache.put(key, key * 7)
                    elif op < 0.9:
                        v = cache.get(key)
                        gets += 1
                        if v is not None and v != key * 7:
                            errors.append(f"wrong value for {key}: {v}")
                    else:
                        v = cache.get_or_compute(key, lambda k: k * 7)
                        computes += 1
                        if v != key * 7:
                            errors.append(f"wrong computed value for {key}: {v}")
                    if len(cache) > capacity:
                        oversize.append(len(cache))
            except Exception as exc:  # noqa: BLE001 - any crash is a failure
                errors.append(repr(exc))
            gets_done.append(gets)
            computes_done.append(computes)

        self.assertTrue(run_threads([lambda s=s: worker(s) for s in range(8)]))
        self.assertEqual(errors, [])
        self.assertEqual(oversize, [])
        self.assertLessEqual(len(cache), capacity)
        s = cache.stats()
        # Every get() is exactly one hit or miss; get_or_compute() calls may count at most once.
        self.assertGreaterEqual(s.hits + s.misses, sum(gets_done))
        self.assertLessEqual(s.hits + s.misses, sum(gets_done) + sum(computes_done))
        self.assertEqual(s.evictions, len(evictions))
