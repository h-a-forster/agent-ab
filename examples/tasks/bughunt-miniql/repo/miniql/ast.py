"""Syntax tree node classes (plain, immutable-ish containers)."""


class Node:
    fields = ()

    def __init__(self, *args):
        if len(args) != len(self.fields):
            raise TypeError("%s expects %d fields" % (type(self).__name__, len(self.fields)))
        for name, value in zip(self.fields, args):
            setattr(self, name, value)

    def __eq__(self, other):
        return type(self) is type(other) and all(getattr(self, f) == getattr(other, f) for f in self.fields)

    def __hash__(self):
        return hash((type(self).__name__,) + tuple(repr(getattr(self, f)) for f in self.fields))

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join(repr(getattr(self, f)) for f in self.fields))


class Literal(Node):
    fields = ("value",)


class Column(Node):
    fields = ("name",)


class Star(Node):
    fields = ()


class Binary(Node):
    """Arithmetic, comparison, AND and OR.  ``op`` is the upper-case operator text."""
    fields = ("op", "left", "right")


class Not(Node):
    fields = ("operand",)


class Negate(Node):
    fields = ("operand",)


class IsNull(Node):
    fields = ("operand", "negated")


class Like(Node):
    fields = ("operand", "pattern", "negated")


class InList(Node):
    fields = ("operand", "items", "negated")


class Between(Node):
    fields = ("operand", "low", "high", "negated")


class Call(Node):
    fields = ("name", "args", "distinct")


class Case(Node):
    fields = ("whens", "default")


class SelectItem(Node):
    fields = ("expr", "alias")


class OrderItem(Node):
    fields = ("expr", "descending")


class Select(Node):
    fields = ("distinct", "items", "table", "where", "group_by", "having", "order_by", "limit", "offset")


AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


def walk(node):
    """Yield ``node`` and every node below it."""
    yield node
    for name in node.fields:
        value = getattr(node, name)
        for child in _children(value):
            yield from walk(child)


def _children(value):
    if isinstance(value, Node):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _children(item)


def contains_aggregate(node):
    return any(isinstance(n, Call) and n.name in AGGREGATES for n in walk(node))
