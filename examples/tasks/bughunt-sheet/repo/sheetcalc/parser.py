"""Formula parser and un-parser."""

from .errors import FormulaSyntaxError
from .refs import parse_ref, shift_ref
from .tokenizer import tokenize

COMPARE = ("=", "<>", "<", "<=", ">", ">=")

# binding strength used when printing a tree back to text
PREC = {"cmp": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "neg": 5, "^": 6}


class Node:
    __slots__ = ()

    def __eq__(self, other):
        return type(self) is type(other) and all(getattr(self, s) == getattr(other, s) for s in self.__slots__)

    def __hash__(self):
        return hash((type(self).__name__,) + tuple(repr(getattr(self, s)) for s in self.__slots__))

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join(repr(getattr(self, s)) for s in self.__slots__))


def _node(name, *fields):
    def __init__(self, *args):
        for f, v in zip(fields, args):
            setattr(self, f, v)

    return type(name, (Node,), {"__slots__": fields, "__init__": __init__})


Num = _node("Num", "value")
Str = _node("Str", "value")
Bool = _node("Bool", "value")
Name = _node("Name", "name")
CellRef = _node("CellRef", "ref")
RangeRef = _node("RangeRef", "start", "end")
Neg = _node("Neg", "operand")
Plus = _node("Plus", "operand")
Binary = _node("Binary", "op", "left", "right")
Call = _node("Call", "name", "args")


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.i = 0

    @property
    def tok(self):
        return self.tokens[self.i]

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def at_op(self, *ops):
        return self.tok.kind == "OP" and self.tok.value in ops

    def expect_op(self, op):
        if not self.at_op(op):
            raise FormulaSyntaxError("expected %r" % op, self.tok.pos)
        self.advance()

    def parse(self):
        node = self.comparison()
        if self.tok.kind != "EOF":
            raise FormulaSyntaxError("unexpected %r" % (self.tok.value,), self.tok.pos)
        return node

    def comparison(self):
        left = self.concat()
        while self.at_op(*COMPARE):
            op = self.advance().value
            left = Binary(op, left, self.concat())
        return left

    def concat(self):
        return self.additive()

    def additive(self):
        left = self.term()
        while self.at_op("+", "-", "&"):
            op = self.advance().value
            left = Binary(op, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.at_op("*", "/"):
            op = self.advance().value
            left = Binary(op, left, self.unary())
        return left

    def unary(self):
        if self.at_op("-"):
            self.advance()
            return Neg(self.unary())
        if self.at_op("+"):
            self.advance()
            return Plus(self.unary())
        return self.power()

    def power(self):
        base = self.primary()
        if self.at_op("^"):
            self.advance()
            return Binary("^", base, self.unary())
        return base

    def primary(self):
        tok = self.tok
        if tok.kind == "NUM":
            self.advance()
            return Num(tok.value)
        if tok.kind == "STR":
            self.advance()
            return Str(tok.value)
        if tok.kind == "REF":
            self.advance()
            ref = parse_ref(tok.value)
            if self.at_op(":"):
                self.advance()
                if self.tok.kind != "REF":
                    raise FormulaSyntaxError("expected a cell after ':'", self.tok.pos)
                end = parse_ref(self.advance().value)
                return RangeRef(ref, end)
            return CellRef(ref)
        if tok.kind == "NAME":
            self.advance()
            if tok.value in ("TRUE", "FALSE"):
                return Bool(tok.value == "TRUE")
            return Name(tok.value)
        if tok.kind == "FUNC":
            self.advance()
            self.expect_op("(")
            args = []
            if not self.at_op(")"):
                args.append(self.comparison())
                while self.at_op(","):
                    self.advance()
                    args.append(self.comparison())
            self.expect_op(")")
            return Call(tok.value, args)
        if self.at_op("("):
            self.advance()
            inner = self.comparison()
            self.expect_op(")")
            return inner
        raise FormulaSyntaxError("unexpected %r" % (tok.value,), tok.pos)


def parse_formula(text):
    """Parse formula text *without* the leading ``=``."""
    return Parser(text).parse()


def walk(node):
    yield node
    if isinstance(node, (Neg, Plus)):
        yield from walk(node.operand)
    elif isinstance(node, Binary):
        yield from walk(node.left)
        yield from walk(node.right)
    elif isinstance(node, Call):
        for arg in node.args:
            yield from walk(arg)


def _prec(node):
    if isinstance(node, Binary):
        return PREC["cmp"] if node.op in COMPARE else PREC[node.op]
    if isinstance(node, (Neg, Plus)):
        return PREC["neg"]
    return 9


def unparse(node):
    """Formula text for a tree (without the leading ``=``), with minimal parentheses."""
    if isinstance(node, Num):
        return repr(node.value)
    if isinstance(node, Str):
        return '"%s"' % node.value.replace('"', '""')
    if isinstance(node, Bool):
        return "TRUE" if node.value else "FALSE"
    if isinstance(node, Name):
        return node.name
    if isinstance(node, CellRef):
        return node.ref.text()
    if isinstance(node, RangeRef):
        return "%s:%s" % (node.start.text(), node.end.text())
    if isinstance(node, (Neg, Plus)):
        inner = unparse(node.operand)
        if _prec(node.operand) < PREC["neg"]:
            inner = "(%s)" % inner
        return ("-" if isinstance(node, Neg) else "+") + inner
    if isinstance(node, Call):
        return "%s(%s)" % (node.name, ",".join(unparse(a) for a in node.args))
    prec = _prec(node)
    right_assoc = node.op == "^"
    left, right = unparse(node.left), unparse(node.right)
    if _prec(node.left) < prec or (_prec(node.left) == prec and right_assoc):
        left = "(%s)" % left
    if _prec(node.right) < prec or (_prec(node.right) == prec and not right_assoc):
        right = "(%s)" % right
    return "%s%s%s" % (left, node.op, right)


class ShiftError(Exception):
    """A shifted reference falls outside the sheet."""


def shift_formula(node, drow, dcol):
    """A copy of the tree with every relative reference moved by (drow, dcol)."""
    if isinstance(node, CellRef):
        ref = shift_ref(node.ref, drow, dcol)
        if ref is None:
            raise ShiftError()
        return CellRef(ref)
    if isinstance(node, RangeRef):
        start, end = shift_ref(node.start, drow, dcol), shift_ref(node.end, drow, dcol)
        if start is None or end is None:
            raise ShiftError()
        return RangeRef(start, end)
    if isinstance(node, Neg):
        return Neg(shift_formula(node.operand, drow, dcol))
    if isinstance(node, Plus):
        return Plus(shift_formula(node.operand, drow, dcol))
    if isinstance(node, Binary):
        return Binary(node.op, shift_formula(node.left, drow, dcol), shift_formula(node.right, drow, dcol))
    if isinstance(node, Call):
        return Call(node.name, [shift_formula(a, drow, dcol) for a in node.args])
    return node
