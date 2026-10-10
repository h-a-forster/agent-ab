"""Reversible edit commands."""


class Command:
    def apply(self, doc):
        raise NotImplementedError

    def revert(self, doc):
        raise NotImplementedError

    def is_noop(self):
        return False

    def merged_with(self, newer):
        """A single command equal to ``self`` followed by ``newer`` (both already applied), or None."""
        return None


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

    def merged_with(self, newer):
        if not isinstance(newer, Insert):
            return None
        if newer.pos != self.pos + len(self.text):
            return None
        if "\n" in newer.text or self.text.endswith("\n"):
            return None
        return Insert(self.pos, self.text + newer.text)

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

    def merged_with(self, newer):
        if not isinstance(newer, Delete):
            return None
        if newer.pos == self.pos:  # forward delete
            merged = Delete(self.pos, self.length + newer.length)
            merged.removed = self.removed + newer.removed
        elif newer.pos + newer.length == self.pos:  # backspace
            merged = Delete(newer.pos, self.length + newer.length)
            merged.removed = newer.removed + self.removed
        else:
            return None
        return merged

    def __repr__(self):
        return f"Delete({self.pos!r}, {self.length!r})"
