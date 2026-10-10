"""TTLCache: bounded cache whose entries expire after a time-to-live."""

import time
from collections import OrderedDict

from .entry import Entry
from .stats import Stats


def _check_ttl(ttl):
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not ttl > 0:
        raise ValueError("ttl must be a positive number")
    return ttl


class TTLCache:
    def __init__(self, capacity, ttl, clock=time.monotonic, sliding=False):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self.ttl = _check_ttl(ttl)
        self.sliding = sliding
        self._clock = clock
        self._data = OrderedDict()
        self._hits = self._misses = self._evictions = self._expirations = self._invalidations = 0

    # -- read-only queries: never change stored entries or statistics ------------------
    def __len__(self):
        now = self._clock()
        return sum(1 for e in self._data.values() if not e.is_expired(now))

    def __contains__(self, key):
        entry = self._data.get(key)
        return entry is not None and not entry.is_expired(self._clock())

    def keys(self):
        """Live keys from least to most recently used."""
        now = self._clock()
        return [k for k, e in self._data.items() if not e.is_expired(now)]

    def peek(self, key, default=None):
        entry = self._data.get(key)
        if entry is None or entry.is_expired(self._clock()):
            return default
        return entry.value

    def ttl_remaining(self, key):
        entry = self._data.get(key)
        now = self._clock()
        if entry is None or entry.is_expired(now):
            return None
        return entry.expires_at - now

    # -- mutations ---------------------------------------------------------------------
    def purge(self):
        """Remove every expired entry; returns how many were removed."""
        now = self._clock()
        dead = [k for k, e in self._data.items() if e.is_expired(now)]
        for k in dead:
            del self._data[k]
        self._expirations += len(dead)
        return len(dead)

    def set(self, key, value, ttl=None, tags=()):
        ttl = self.ttl if ttl is None else _check_ttl(ttl)
        self.purge()
        if key in self._data:
            del self._data[key]
        elif len(self._data) >= self.capacity:
            self._data.popitem(last=False)
            self._evictions += 1
        self._data[key] = Entry(value, ttl, self._clock() + ttl, frozenset(tags))

    def _live(self, key):
        """The live entry for ``key``; an expired one is removed and counted."""
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry.is_expired(self._clock()):
            del self._data[key]
            self._expirations += 1
            return None
        return entry

    def get(self, key, default=None):
        entry = self._live(key)
        if entry is None:
            self._misses += 1
            return default
        self._data.move_to_end(key)
        self._hits += 1
        if self.sliding:
            entry.expires_at = self._clock() + entry.ttl
        return entry.value

    def touch(self, key, ttl=None):
        """Restart the expiry clock of a live entry (optionally with a new ttl)."""
        if ttl is not None:
            _check_ttl(ttl)
        entry = self._live(key)
        if entry is None:
            return False
        if ttl is not None:
            entry.ttl = ttl
        entry.expires_at = self._clock() + entry.ttl
        return True

    def delete(self, key):
        return self._live(key) is not None and self._data.pop(key) is not None

    def invalidate_tag(self, tag):
        """Remove every entry carrying ``tag``; returns the number of live entries removed."""
        now = self._clock()
        removed = 0
        for k in [k for k, e in self._data.items() if tag in e.tags]:
            if self._data[k].is_expired(now):
                self._expirations += 1
            else:
                removed += 1
            del self._data[k]
        self._invalidations += removed
        return removed

    def stats(self):
        return Stats(self._hits, self._misses, self._evictions, self._expirations, self._invalidations)
