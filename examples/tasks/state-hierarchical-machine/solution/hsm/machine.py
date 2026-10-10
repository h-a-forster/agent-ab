"""The (hierarchical) state machine."""

from .states import StateSet


class Machine:
    def __init__(self, states, transitions, initial, on_enter=None, on_exit=None, initials=None):
        self._states = StateSet(states, initials)
        self._states.check(initial)
        self._on_enter = dict(on_enter or {})
        self._on_exit = dict(on_exit or {})
        for name in list(self._on_enter) + list(self._on_exit):
            self._states.check(name)
        self._by_key = {}
        for t in transitions:
            self._states.check(t.source)
            if t.target is not None:
                self._states.check(t.target)
            self._by_key.setdefault((t.source, t.event), []).append(t)
        path = self._states.descent(initial)
        # enter ancestors of ``initial`` first, then ``initial`` and its default descent
        for name in reversed(self._states.lineage(initial)[1:]):
            self._enter(name, {})
        for name in path:
            self._enter(name, {})
        self._state = path[-1]

    @property
    def state(self):
        return self._state

    def is_in(self, name):
        return name in self._states.lineage(self._state)

    def configuration(self):
        return list(reversed(self._states.lineage(self._state)))

    def send(self, event, **payload):
        for src in self._states.lineage(self._state):
            for t in self._by_key.get((src, event), ()):
                if t.guard is not None and not t.guard(payload):
                    continue
                self._fire(t, payload)
                return True
        return False

    def _fire(self, t, payload):
        if t.target is None:
            if t.action:
                t.action(payload)
            return
        lca = self._states.lca(t.source, t.target)
        for name in self._states.lineage(self._state):
            if name == lca:
                break
            self._exit(name, payload)
        if t.action:
            t.action(payload)
        below = []
        for name in self._states.lineage(t.target):
            if name == lca:
                break
            below.append(name)
        below.reverse()
        descent = self._states.descent(t.target)
        for name in below + descent[1:]:
            self._enter(name, payload)
        self._state = descent[-1]

    def _enter(self, name, payload):
        cb = self._on_enter.get(name)
        if cb:
            cb(payload)

    def _exit(self, name, payload):
        cb = self._on_exit.get(name)
        if cb:
            cb(payload)
