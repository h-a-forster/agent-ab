"""Undo/redo history."""


class History:
    def __init__(self, doc):
        self.doc = doc
        self._undo = []
        self._redo = []
        self._saved_depth = 0

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    @property
    def is_dirty(self):
        return len(self._undo) != self._saved_depth

    def mark_saved(self):
        self._saved_depth = len(self._undo)

    def execute(self, command):
        command.apply(self.doc)
        self._undo.append(command)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            return False
        command = self._undo.pop()
        command.revert(self.doc)
        self._redo.append(command)
        return True

    def redo(self):
        if not self._redo:
            return False
        command = self._redo.pop()
        command.apply(self.doc)
        self._undo.append(command)
        return True
