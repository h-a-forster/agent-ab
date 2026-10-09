"""A bounded, thread-safe least-recently-used cache."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Hashable

_MISSING = object()


@dataclass(frozen=True)
class CacheStats:
    hits: int
    misses: int
    evictions: int


class _Pending:
    """An in-flight ``get_or_compute`` for one key; waiters block on ``done``."""

    __slots__ = ("done", "value", "failed")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Any = None
        self.failed = False


class LRUCache:
    """Keep at most ``capacity`` entries, evicting the least recently used one first.

    ``on_evict(key, value)`` is called for every entry removed to make room for a new one.
    All methods are thread-safe. Callbacks and ``compute`` functions run without the internal
    lock held, so they may use the cache themselves.
    """

    def __init__(self, capacity: int, on_evict: Callable[[Hashable, Any], None] | None = None):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self.on_evict = on_evict
        self._lock = threading.Lock()
        self._data: OrderedDict[Hashable, Any] = OrderedDict()  # oldest first
        self._pending: dict[Hashable, _Pending] = {}
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._data

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Return the cached value (marking it recently used) or ``default``."""
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._hits += 1
                return self._data[key]
            self._misses += 1
            return default

    def peek(self, key: Hashable, default: Any = None) -> Any:
        """Return the cached value without touching recency or statistics."""
        with self._lock:
            return self._data.get(key, default)

    def put(self, key: Hashable, value: Any) -> None:
        """Insert or replace ``key``; evict the least recently used entry if over capacity."""
        with self._lock:
            evicted = self._put_locked(key, value)
        self._notify(evicted)

    def _put_locked(self, key: Hashable, value: Any) -> list[tuple[Hashable, Any]]:
        if key in self._data:
            self._data[key] = value
            self._data.move_to_end(key)
            return []
        self._data[key] = value
        evicted = []
        while len(self._data) > self.capacity:
            evicted.append(self._data.popitem(last=False))
            self._evictions += 1
        return evicted

    def _notify(self, evicted: list[tuple[Hashable, Any]]) -> None:
        if self.on_evict is not None:
            for key, value in evicted:
                self.on_evict(key, value)

    def get_or_compute(self, key: Hashable, compute: Callable[[Hashable], Any]) -> Any:
        """Return the cached value for ``key``, computing and caching it on a miss.

        Concurrent misses on the same key share one call to ``compute``.
        """
        while True:
            with self._lock:
                if key in self._data:
                    self._data.move_to_end(key)
                    self._hits += 1
                    return self._data[key]
                pending = self._pending.get(key)
                owner = pending is None
                if owner:
                    pending = self._pending[key] = _Pending()
                    self._misses += 1
            if owner:
                break
            pending.done.wait()
            if not pending.failed:
                return pending.value
            # The computing thread failed; try again (possibly becoming the owner).

        try:
            value = compute(key)
        except BaseException:
            with self._lock:
                del self._pending[key]
            pending.failed = True
            pending.done.set()
            raise
        with self._lock:
            evicted = self._put_locked(key, value)
            del self._pending[key]
        pending.value = value
        pending.done.set()
        self._notify(evicted)
        return value

    def clear(self) -> None:
        """Remove every entry (no eviction callbacks). Statistics are kept."""
        with self._lock:
            self._data.clear()

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._hits, self._misses, self._evictions)
