"""A cache entry."""

from dataclasses import dataclass


@dataclass
class Entry:
    value: object
    expires_at: float

    def is_expired(self, now):
        return now >= self.expires_at
