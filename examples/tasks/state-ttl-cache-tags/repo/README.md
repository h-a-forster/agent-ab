# ttlstore

In-process cache with time-to-live and LRU eviction, used by the pricing service. Time comes
from an injectable clock (a zero-argument callable returning seconds), so tests never sleep.

```python
from ttlstore import TTLCache
from ttlstore.clock import ManualClock

clock = ManualClock()
cache = TTLCache(capacity=2, ttl=10, clock=clock)
cache.set("a", 1)
clock.advance(5)
cache.get("a")        # 1
clock.advance(5)
cache.get("a")        # None, expired
```

* `entry.py`   `Entry`: a stored value with its expiry
* `stats.py`   `Stats`: counters returned by `cache.stats()`
* `cache.py`   `TTLCache`
* `clock.py`   `ManualClock` for tests

Run the tests with `python -m unittest discover -s tests -t .`.
