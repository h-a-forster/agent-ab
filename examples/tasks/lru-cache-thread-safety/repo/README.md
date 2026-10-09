# keepcache

Small in-process caches for a web service: `LRUCache` keeps the most recently used entries
up to a fixed capacity and reports hit/miss/eviction statistics.

```python
from keepcache import LRUCache

cache = LRUCache(2)
cache.put("a", 1)
cache.put("b", 2)
cache.get("a")                 # 1
cache.put("c", 3)              # evicts "b", the least recently used
cache.get_or_compute("d", lambda key: expensive(key))
```

Run the tests with `python -m unittest discover -s tests -t .`.
