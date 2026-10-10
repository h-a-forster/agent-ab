"""Undo/redo history."""

import itertools
from contextlib import contextmanager


class _Step:
    def __init__(self, commands, before_id, after_id, mergeable):
        self.commands = commands
        self.before_id = before_id
        self.after_id = after_id
        self.mergeable = mergeable


class History:
    def __init__(self, doc, limit=None):
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            raise ValueError("limit must be a positive integer or None")
        self.doc = doc
        self.limit = limit
        self._ids = itertools.count(1)
        self._base_id = 0  # state before the oldest remembered step
        self._saved_id = 0
        self._undo = []
        self._redo = []
        self._can_merge = False
        self._depth = 0
        self._tx = None

    # -- state ids: every distinct history point has a unique id ------------------------
    def _current_id(self):
        return self._undo[-1].after_id if self._undo else self._base_id

    @property
    def can_undo(self):
        return bool(self._undo)

    @property
    def can_redo(self):
        return bool(self._redo)

    @property
    def undo_depth(self):
        return len(self._undo)

    @property
    def redo_depth(self):
        return len(self._redo)

    @property
    def is_dirty(self):
        return self._current_id() != self._saved_id

    def _no_tx(self):
        if self._depth:
            raise RuntimeError("not allowed inside a transaction")

    def mark_saved(self):
        self._no_tx()
        self._saved_id = self._current_id()
        self._can_merge = False

    def break_coalescing(self):
        self._can_merge = False

    def _push(self, step):
        self._undo.append(step)
        self._redo.clear()
        if self.limit is not None:
            while len(self._undo) > self.limit:
                self._base_id = self._undo.pop(0).after_id

    def execute(self, command):
        if command.is_noop():
            return
        command.apply(self.doc)
        if self._depth:
            self._tx.append(command)
            return
        if self._can_merge and self._undo and self._undo[-1].mergeable:
            top = self._undo[-1]
            merged = top.commands[0].merged_with(command)
            if merged is not None:
                top.commands = [merged]
                top.after_id = next(self._ids)
                self._redo.clear()
                return
        step = _Step([command], self._current_id(), next(self._ids), True)
        self._push(step)
        self._can_merge = True

    @contextmanager
    def transaction(self):
        outer = self._depth == 0
        if outer:
            self._tx = []
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if outer:
                done, self._tx = self._tx, None
                for command in reversed(done):
                    command.revert(self.doc)
            raise
        else:
            self._depth -= 1
            if outer:
                done, self._tx = self._tx, None
                if done:
                    self._push(_Step(done, self._current_id(), next(self._ids), False))
                self._can_merge = False

    def undo(self):
        self._no_tx()
        self._can_merge = False
        if not self._undo:
            return False
        step = self._undo.pop()
        for command in reversed(step.commands):
            command.revert(self.doc)
        self._redo.append(step)
        return True

    def redo(self):
        self._no_tx()
        self._can_merge = False
        if not self._redo:
            return False
        step = self._redo.pop()
        for command in step.commands:
            command.apply(self.doc)
        self._undo.append(step)
        return True
