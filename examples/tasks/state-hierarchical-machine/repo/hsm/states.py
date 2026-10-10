"""Declared states."""


class StateSet:
    def __init__(self, names):
        names = list(names)
        if len(set(names)) != len(names):
            raise ValueError("duplicate state names")
        if not names:
            raise ValueError("at least one state is required")
        self.names = tuple(names)

    def check(self, name):
        if name not in self.names:
            raise ValueError(f"unknown state {name!r}")
        return name
