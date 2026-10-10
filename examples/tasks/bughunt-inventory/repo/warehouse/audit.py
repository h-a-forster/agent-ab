"""An append-only event log."""


class Event:
    def __init__(self, seq, kind, data):
        self.seq = seq
        self.kind = kind
        self.data = data

    def __repr__(self):
        return "Event(%d %s)" % (self.seq, self.kind)


class AuditLog:
    def __init__(self):
        self._events = []

    def log(self, kind, **data):
        event = Event(len(self._events) + 1, kind, dict(data))
        self._events.append(event)
        return event

    def events(self, kind=None):
        return [e for e in self._events if kind is None or e.kind == kind]

    def last(self, kind=None):
        found = self.events(kind)
        return found[-1] if found else None

    def __len__(self):
        return len(self._events)
