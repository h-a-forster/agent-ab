"""The state machine."""

from .states import StateSet


class Machine:
    def __init__(self, states, transitions, initial, on_enter=None, on_exit=None):
        self._states = StateSet(states)
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
        self._state = initial
        self._enter(initial, {})

    @property
    def state(self):
        return self._state

    def is_in(self, name):
        return self._state == name

    def configuration(self):
        return [self._state]

    def send(self, event, **payload):
        """Dispatch an event. Returns True if a transition fired, False if it was ignored."""
        for t in self._by_key.get((self._state, event), ()):
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
        self._exit(self._state, payload)
        if t.action:
            t.action(payload)
        self._state = t.target
        self._enter(t.target, payload)

    def _enter(self, name, payload):
        cb = self._on_enter.get(name)
        if cb:
            cb(payload)

    def _exit(self, name, payload):
        cb = self._on_exit.get(name)
        if cb:
            cb(payload)
