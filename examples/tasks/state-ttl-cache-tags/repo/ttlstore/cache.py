"""TTLCache: bounded cache whose entries expire after a time-to-live."""

import time
from collections import OrderedDict

from .entry import Entry
from .stats import Stats


class TTLCache:
    def __init__(self, capacity, ttl, clock=time.monotonic):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        if ttl <= 0:
            raise ValueError("ttl must be positive")
        self.capacity = capacity
        self.ttl = ttl
        self._clock = clock
        self._data = OrderedDict()
        self._hits = self._misses = self._evictions = self._expirations = 0

    def __len__(self):
        return len(self._data)

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        """Keys from least to most recently used."""
        return list(self._data)

    def set(self, key, value):
        now = self._clock()
        if key in self._data:
            del self._data[key]
        elif len(self._data) >= self.capacity:
            self._data.popitem(last=False)
            self._evictions += 1
        self._data[key] = Entry(value, now + self.ttl)

    def get(self, key, default=None):
        entry = self._data.get(key)
        if entry is None:
            self._misses += 1
            return default
        if entry.is_expired(self._clock()):
            del self._data[key]
            self._expirations += 1
            self._misses += 1
            return default
        self._data.move_to_end(key)
        self._hits += 1
        return entry.value

    def delete(self, key):
        return self._data.pop(key, None) is not None

    def stats(self):
        return Stats(self._hits, self._misses, self._evictions, self._expirations)
