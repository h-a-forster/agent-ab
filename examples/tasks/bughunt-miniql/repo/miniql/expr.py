"""Expression evaluation against a row or a group of rows."""

from . import aggregates, ast, values
from .errors import ExecError


class RowContext:
    """Evaluation context for one row.

    ``aliases`` maps SELECT-list aliases to their values.  ``alias_first`` decides which
    one wins when a name is both a column and an alias (False: the column wins).
    """

    def __init__(self, row, aliases=None, alias_first=False):
        self.row = row
        self.aliases = aliases or {}
        self.alias_first = alias_first

    def lookup(self, name):
        if self.alias_first and name in self.aliases:
            return self.aliases[name]
        if name in self.row:
            return self.row[name]
        if name in self.aliases:
            return self.aliases[name]
        raise ExecError("unknown column %r" % name)

    def rows(self):
        return [self.row]

    def with_aliases(self, aliases, alias_first=False):
        return RowContext(self.row, aliases, alias_first)


class GroupContext:
    """Evaluation context for a group of rows (aggregates see every row)."""

    def __init__(self, group_rows, aliases=None, alias_first=False):
        self.group_rows = group_rows
        self.aliases = aliases or {}
        self.alias_first = alias_first
        self.row = group_rows[0] if group_rows else {}

    def lookup(self, name):
        if self.alias_first and name in self.aliases:
            return self.aliases[name]
        if name in self.row:
            return self.row[name]
        if name in self.aliases:
            return self.aliases[name]
        if not self.group_rows:
            return None
        raise ExecError("unknown column %r" % name)

    def rows(self):
        return self.group_rows

    def with_aliases(self, aliases, alias_first=False):
        return GroupContext(self.group_rows, aliases, alias_first)


def evaluate(node, ctx):
    if isinstance(node, ast.Literal):
        return node.value
    if isinstance(node, ast.Column):
        return ctx.lookup(node.name)
    if isinstance(node, ast.Negate):
        value = evaluate(node.operand, ctx)
        return None if value is None else -value
    if isinstance(node, ast.Not):
        return values.tv_not(truth(evaluate(node.operand, ctx)))
    if isinstance(node, ast.Binary):
        return _binary(node, ctx)
    if isinstance(node, ast.IsNull):
        result = evaluate(node.operand, ctx) is None
        return not result if node.negated else result
    if isinstance(node, ast.Like):
        result = values.like(evaluate(node.operand, ctx), evaluate(node.pattern, ctx))
        return values.tv_not(result) if node.negated else result
    if isinstance(node, ast.InList):
        result = values.in_list(evaluate(node.operand, ctx), [evaluate(i, ctx) for i in node.items])
        return values.tv_not(result) if node.negated else result
    if isinstance(node, ast.Between):
        operand = evaluate(node.operand, ctx)
        low = values.compare(">=", operand, evaluate(node.low, ctx))
        high = values.compare("<=", operand, evaluate(node.high, ctx))
        result = values.tv_and(low, high)
        return values.tv_not(result) if node.negated else result
    if isinstance(node, ast.Case):
        for cond, result in node.whens:
            if truth(evaluate(cond, ctx)) is True:
                return evaluate(result, ctx)
        return evaluate(node.default, ctx) if node.default is not None else None
    if isinstance(node, ast.Call):
        return _call(node, ctx)
    raise ExecError("cannot evaluate %r" % (node,))


def truth(value):
    """Coerce a value to True/False/None for logic operators."""
    if value is None or isinstance(value, bool):
        return value
    raise ExecError("expected a boolean, got %r" % (value,))


def _binary(node, ctx):
    op = node.op
    if op == "AND":
        left = truth(evaluate(node.left, ctx))
        if left is False:
            return False
        return values.tv_and(left, truth(evaluate(node.right, ctx)))
    if op == "OR":
        left = truth(evaluate(node.left, ctx))
        if left is True:
            return True
        return values.tv_or(left, truth(evaluate(node.right, ctx)))
    left = evaluate(node.left, ctx)
    right = evaluate(node.right, ctx)
    if op in ("=", "<>", "<", "<=", ">", ">="):
        return values.compare(op, left, right)
    return values.arithmetic(op, left, right)


def _call(node, ctx):
    name = node.name
    if name in ast.AGGREGATES:
        return _aggregate(node, ctx)
    args = [evaluate(a, ctx) for a in node.args]
    if name == "COALESCE":
        for arg in args:
            if arg is not None:
                return arg
        return None
    if any(a is None for a in args):
        return None
    if name == "UPPER":
        return _text(args, 1, name)[0].upper()
    if name == "LOWER":
        return _text(args, 1, name)[0].lower()
    if name == "TRIM":
        return _text(args, 1, name)[0].strip()
    if name == "LENGTH":
        return len(_text(args, 1, name)[0])
    if name == "ABS":
        _arity(args, 1, name)
        return abs(args[0])
    if name == "ROUND":
        if len(args) not in (1, 2):
            raise ExecError("ROUND takes 1 or 2 arguments")
        digits = args[1] if len(args) == 2 else 0
        return _round_half_up(args[0], digits)
    if name == "SUBSTR":
        if len(args) not in (2, 3):
            raise ExecError("SUBSTR takes 2 or 3 arguments")
        text, start = args[0], args[1]
        begin = max(start - 1, 0)
        return text[begin:] if len(args) == 2 else text[begin:begin + args[2]]
    raise ExecError("unknown function %s" % name)


def _arity(args, count, name):
    if len(args) != count:
        raise ExecError("%s takes %d argument(s)" % (name, count))


def _text(args, count, name):
    _arity(args, count, name)
    if not isinstance(args[0], str):
        raise ExecError("%s needs text" % name)
    return args


def _round_half_up(value, digits):
    from decimal import ROUND_HALF_UP, Decimal

    quantum = Decimal(1).scaleb(-digits)
    result = Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(result) if digits <= 0 and isinstance(value, int) else float(result)


def _aggregate(node, ctx):
    if node.args and isinstance(node.args[0], ast.Star):
        if node.name != "COUNT":
            raise ExecError("only COUNT accepts *")
        return aggregates.count_star(ctx.rows())
    if len(node.args) != 1:
        raise ExecError("%s takes one argument" % node.name)
    inner = RowContext
    collected = [evaluate(node.args[0], inner(row)) for row in ctx.rows()]
    return aggregates.apply(node.name, collected, node.distinct)


def unparse(node):
    """Readable text for an expression, used as the default output column name."""
    if isinstance(node, ast.Literal):
        if node.value is None:
            return "NULL"
        if isinstance(node.value, str):
            return "'%s'" % node.value.replace("'", "''")
        return str(node.value)
    if isinstance(node, ast.Column):
        return node.name
    if isinstance(node, ast.Star):
        return "*"
    if isinstance(node, ast.Negate):
        return "-" + unparse(node.operand)
    if isinstance(node, ast.Not):
        return "NOT " + unparse(node.operand)
    if isinstance(node, ast.Binary):
        return "(%s %s %s)" % (unparse(node.left), node.op, unparse(node.right))
    if isinstance(node, ast.Call):
        inner = ", ".join(unparse(a) for a in node.args)
        return "%s(%s%s)" % (node.name, "DISTINCT " if node.distinct else "", inner)
    return type(node).__name__.upper()
