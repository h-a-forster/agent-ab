"""Tree-walking evaluator."""

from . import parser as P
from .errors import DIV0, NAME, REF, VALUE, CellError, ErrorSignal
from .functions import RangeValue, call, is_number, power, to_number, to_text
from .refs import SheetError, expand_range, range_shape

TYPE_RANK = {"number": 0, "text": 1, "bool": 2}


def _kind(v):
    if isinstance(v, bool):
        return "bool"
    if is_number(v):
        return "number"
    return "text"


def compare_values(op, a, b):
    """Excel-like comparison: empty cells equal 0 or "", text compares case-insensitively and
    numbers sort before text before booleans."""
    if a is None:
        a = "" if isinstance(b, str) else (False if isinstance(b, bool) else 0)
    if b is None:
        b = "" if isinstance(a, str) else (False if isinstance(a, bool) else 0)
    ka, kb = _kind(a), _kind(b)
    if ka != kb:
        left, right = TYPE_RANK[ka], TYPE_RANK[kb]
    elif ka == "text":
        left, right = a.lower(), b.lower()
    else:
        left, right = a, b
    return {"=": left == right, "<>": left != right, "<": left < right,
            "<=": left <= right, ">": left > right, ">=": left >= right}[op]


class Evaluator:
    """Evaluates parsed formulas.  ``lookup(key)`` supplies cell values."""

    def __init__(self, lookup):
        self.lookup = lookup

    def evaluate(self, node):
        """Value of the tree; may be a CellError (never raises ErrorSignal)."""
        try:
            value = self.eval(node)
        except ErrorSignal as signal:
            return signal.error
        if isinstance(value, RangeValue):
            return VALUE
        return value

    def eval(self, node):
        if isinstance(node, P.Num) or isinstance(node, P.Str) or isinstance(node, P.Bool):
            return node.value
        if isinstance(node, P.Name):
            raise ErrorSignal(REF if node.name == "#REF!" else NAME)
        if isinstance(node, P.CellRef):
            return self.lookup(node.ref.key)
        if isinstance(node, P.RangeRef):
            try:
                keys = expand_range(node.start, node.end)
            except SheetError:
                raise ErrorSignal(REF) from None
            rows, cols = range_shape(node.start, node.end)
            return RangeValue([self.lookup(k) for k in keys], rows, cols)
        if isinstance(node, P.Neg):
            return -to_number(self.scalar(node.operand))
        if isinstance(node, P.Plus):
            return to_number(self.scalar(node.operand))
        if isinstance(node, P.Binary):
            return self.binary(node)
        if isinstance(node, P.Call):
            return self.call(node)
        raise ErrorSignal(VALUE)

    def scalar(self, node):
        value = self.eval(node)
        if isinstance(value, RangeValue):
            raise ErrorSignal(VALUE)
        if isinstance(value, CellError):
            raise ErrorSignal(value)
        return value

    def binary(self, node):
        op = node.op
        a, b = self.scalar(node.left), self.scalar(node.right)
        if op == "&":
            return to_text(a) + to_text(b)
        if op in P.COMPARE:
            return compare_values(op, a, b)
        x, y = to_number(a), to_number(b)
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            if y == 0:
                raise ErrorSignal(DIV0)
            result = x / y
            return int(result) if isinstance(x, int) and isinstance(y, int) and x % y == 0 else result
        return power(x, y)

    def call(self, node):
        name = node.name
        if name == "IF":
            return self.if_(node.args)
        if name == "IFERROR":
            return self.iferror(node.args)
        return call(name, [self.eval(arg) for arg in node.args])

    def if_(self, args):
        if not 2 <= len(args) <= 3:
            raise ErrorSignal(VALUE)
        from .functions import to_bool

        if to_bool(self.scalar(args[0])):
            return self.scalar(args[1])
        return self.scalar(args[2]) if len(args) == 3 else False

    def iferror(self, args):
        if len(args) != 2:
            raise ErrorSignal(VALUE)
        try:
            value = self.scalar(args[0])
        except ErrorSignal:
            return self.scalar(args[1])
        return value
