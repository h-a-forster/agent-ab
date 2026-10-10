"""Parse results."""


class Namespace:
    def __init__(self, values):
        object.__setattr__(self, "_values", dict(values))

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None

    def __getitem__(self, key):
        return self._values[key]

    def __contains__(self, key):
        return key in self._values

    def to_dict(self):
        return dict(self._values)

    def __repr__(self):
        return f"Namespace({self._values!r})"
