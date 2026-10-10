"""The record type that flows through the pipeline."""


class Record:
    def __init__(self, ts, level, msg, host=None, fields=None, raw=None, lineno=None):
        self.ts = ts
        self.level = level
        self.msg = msg
        self.host = host
        self.fields = fields if fields is not None else {}
        self.raw = raw
        self.lineno = lineno

    def get(self, name, default=None):
        """A top-level attribute (ts, level, msg, host) or an entry of ``fields``."""
        if name in ("ts", "level", "msg", "host"):
            return getattr(self, name)
        return self.fields.get(name, default)

    def as_dict(self):
        out = {"ts": self.ts, "level": self.level, "msg": self.msg, "host": self.host}
        out.update(self.fields)
        return out

    def __repr__(self):
        return "Record(%s %s %r)" % (self.ts, self.level, self.msg)
