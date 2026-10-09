"""A bounded least-recently-used cache."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Hashable

_MISSING = object()


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int


class LRUCache:
    """Keep at most ``capacity`` entries, evicting the least recently used one first.

    ``on_evict(key, value)`` is called for every entry removed to make room for a new one.
    """

    def __init__(self, capacity: int, on_evict: Callable[[Hashable, Any], None] | None = None):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self.on_evict = on_evict
        self._data: dict[Hashable, Any] = {}
        self._order: list[Hashable] = []  # oldest first
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: Hashable) -> bool:
        return key in self._data

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Return the cached value (marking it recently used) or ``default``."""
        if key in self._data:
            self._hits += 1
            return self._data[key]
        self._misses += 1
        return default

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """Return the cached value without touching recency or statistics."""
        return self._data.get(key, default)

    def put(self, key: Hashable, value: Any) -> None:
        """Insert or replace ``key``; evict the least recently used entry if over capacity."""
        self._data[key] = value
        self._order.append(key)
        if len(self._order) > self.capacity:
            oldest = self._order.pop(0)
            evicted = self._data.pop(oldest)
            self._evictions += 1
            if self.on_evict is not None:
                self.on_evict(oldest, evicted)

    def get_or_compute(self, key: Hashable, compute: Callable[[Hashable], Any]) -> Any:
        """Return the cached value for ``key``, computing and caching it on a miss."""
        value = self.get(key, _MISSING)
        if value is _MISSING:
            value = compute(key)
            self.put(key, value)
        return value

    def clear(self) -> None:
        """Remove every entry (no eviction callbacks). Statistics are kept."""
        self._data.clear()
        self._order.clear()

    def stats(self) -> CacheStats:
        return CacheStats(self._hits, self._misses, self._evictions)
