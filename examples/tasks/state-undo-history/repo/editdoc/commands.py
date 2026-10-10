"""Reversible edit commands."""


class Command:
    def apply(self, doc):
        raise NotImplementedError

    def revert(self, doc):
        raise NotImplementedError

    def is_noop(self):
        return False


class Insert(Command):
    def __init__(self, pos, text):
        self.pos = pos
        self.text = text

    def is_noop(self):
        return self.text == ""

    def apply(self, doc):
        doc.insert(self.pos, self.text)

    def revert(self, doc):
        doc.delete(self.pos, len(self.text))

    def __repr__(self):
        return f"Insert({self.pos!r}, {self.text!r})"


class Delete(Command):
    def __init__(self, pos, length):
        self.pos = pos
        self.length = length
        self.removed = None

    def is_noop(self):
        return self.length == 0

    def apply(self, doc):
        self.removed = doc.delete(self.pos, self.length)

    def revert(self, doc):
        doc.insert(self.pos, self.removed)

    def __repr__(self):
        return f"Delete({self.pos!r}, {self.length!r})"
