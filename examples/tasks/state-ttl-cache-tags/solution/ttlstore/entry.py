"""A cache entry."""

from dataclasses import dataclass


@dataclass
class Entry:
    value: object
    ttl: float
    expires_at: float
    tags: frozenset = frozenset()

    def is_expired(self, now):
        return now >= self.expires_at
