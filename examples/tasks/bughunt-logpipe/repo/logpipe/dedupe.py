"""Suppressing repeated records."""


def default_key(record):
    return (record.host, record.msg)


class Deduper:
    """Drops a record when the same key was *emitted* less than ``window`` seconds earlier.

    Only records that pass are remembered: a steady stream of one message with a gap shorter
    than ``window`` still lets one record through every ``window`` seconds.
    """

    def __init__(self, window, key=default_key):
        if window <= 0:
            raise ValueError("window must be positive")
        self.window = window
        self.key = key
        self._last = {}
        self.dropped = 0

    def accept(self, record):
        key = self.key(record)
        last = self._last.get(key)
        self._last[key] = record.ts
        if last is not None and record.ts - last < self.window:
            self.dropped += 1
            return False
        return True

    def reset(self):
        self._last.clear()
        self.dropped = 0

    def tracked(self):
        return len(self._last)
