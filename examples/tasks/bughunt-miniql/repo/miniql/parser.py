"""Recursive-descent parser: tokens -> ``Select`` tree."""

from . import ast
from .errors import ParseError
from .tokens import tokenize

COMPARISONS = ("=", "<>", "<", "<=", ">", ">=")


class Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.i = 0

    # -- token helpers -----------------------------------------------------
    @property
    def tok(self):
        return self.tokens[self.i]

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def at_keyword(self, *words):
        return self.tok.kind == "KEYWORD" and self.tok.value in words

    def at_op(self, *ops):
        return self.tok.kind == "OP" and self.tok.value in ops

    def accept_keyword(self, word):
        if self.at_keyword(word):
            self.advance()
            return True
        return False

    def accept_op(self, op):
        if self.at_op(op):
            self.advance()
            return True
        return False

    def expect_keyword(self, word):
        if not self.accept_keyword(word):
            raise ParseError("expected %s" % word, self.tok.pos)

    def expect_op(self, op):
        if not self.accept_op(op):
            raise ParseError("expected %r" % op, self.tok.pos)

    def expect_ident(self):
        if self.tok.kind != "IDENT":
            raise ParseError("expected a name", self.tok.pos)
        return self.advance().value

    # -- statements --------------------------------------------------------
    def parse_select(self):
        self.expect_keyword("SELECT")
        distinct = self.accept_keyword("DISTINCT")
        items = [self.parse_item()]
        while self.accept_op(","):
            items.append(self.parse_item())
        self.expect_keyword("FROM")
        table = self.expect_ident()
        where = self.parse_expr() if self.accept_keyword("WHERE") else None
        group_by = []
        if self.accept_keyword("GROUP"):
            self.expect_keyword("BY")
            group_by.append(self.parse_expr())
            while self.accept_op(","):
                group_by.append(self.parse_expr())
        having = self.parse_expr() if self.accept_keyword("HAVING") else None
        order_by = []
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            order_by.append(self.parse_order_item())
            while self.accept_op(","):
                order_by.append(self.parse_order_item())
        limit = offset = None
        if self.accept_keyword("LIMIT"):
            limit = self.parse_count("LIMIT")
            if self.accept_keyword("OFFSET"):
                offset = self.parse_count("OFFSET")
        elif self.accept_keyword("OFFSET"):
            offset = self.parse_count("OFFSET")
        if self.tok.kind != "EOF":
            raise ParseError("unexpected %r" % (self.tok.value,), self.tok.pos)
        return ast.Select(distinct, items, table, where, group_by, having, order_by, limit, offset)

    def parse_count(self, what):
        tok = self.advance()
        if tok.kind != "NUMBER" or not isinstance(tok.value, int):
            raise ParseError("%s needs a whole number" % what, tok.pos)
        return tok.value

    def parse_item(self):
        if self.at_op("*"):
            self.advance()
            return ast.SelectItem(ast.Star(), None)
        expr = self.parse_expr()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.expect_ident()
        return ast.SelectItem(expr, alias)

    def parse_order_item(self):
        expr = self.parse_expr()
        descending = False
        if self.accept_keyword("DESC"):
            descending = True
        else:
            self.accept_keyword("ASC")
        return ast.OrderItem(expr, descending)

    # -- expressions, loosest binding first ----------------------------------
    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_not()
        while self.at_keyword("AND", "OR"):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_not())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.accept_keyword("AND"):
            left = ast.Binary("AND", left, self.parse_not())
        return left

    def parse_not(self):
        if self.accept_keyword("NOT"):
            return ast.Not(self.parse_not())
        return self.parse_predicate()

    def parse_predicate(self):
        left = self.parse_additive()
        while True:
            if self.at_op(*COMPARISONS):
                op = self.advance().value
                left = ast.Binary(op, left, self.parse_additive())
                continue
            if self.at_keyword("IS"):
                self.advance()
                negated = self.accept_keyword("NOT")
                self.expect_keyword("NULL")
                left = ast.IsNull(left, negated)
                continue
            negated = False
            if self.at_keyword("NOT") and self.tokens[self.i + 1].kind == "KEYWORD" \
                    and self.tokens[self.i + 1].value in ("LIKE", "IN", "BETWEEN"):
                self.advance()
                negated = True
            if self.accept_keyword("LIKE"):
                left = ast.Like(left, self.parse_additive(), negated)
            elif self.accept_keyword("IN"):
                self.expect_op("(")
                items = [self.parse_expr()]
                while self.accept_op(","):
                    items.append(self.parse_expr())
                self.expect_op(")")
                left = ast.InList(left, items, negated)
            elif self.accept_keyword("BETWEEN"):
                low = self.parse_additive()
                self.expect_keyword("AND")
                high = self.parse_additive()
                left = ast.Between(left, low, high, negated)
            else:
                return left

    def parse_additive(self):
        left = self.parse_term()
        while self.at_op("+", "-"):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_term())
        return left

    def parse_term(self):
        left = self.parse_unary()
        while self.at_op("*", "/", "%"):
            op = self.advance().value
            left = ast.Binary(op, left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.accept_op("-"):
            return ast.Negate(self.parse_unary())
        if self.accept_op("+"):
            return self.parse_unary()
        return self.parse_primary()

    def parse_primary(self):
        tok = self.tok
        if tok.kind == "NUMBER" or tok.kind == "STRING":
            self.advance()
            return ast.Literal(tok.value)
        if tok.kind == "KEYWORD":
            if tok.value in ("NULL", "TRUE", "FALSE"):
                self.advance()
                return ast.Literal({"NULL": None, "TRUE": True, "FALSE": False}[tok.value])
            if tok.value == "CASE":
                return self.parse_case()
        if tok.kind == "OP" and tok.value == "(":
            self.advance()
            inner = self.parse_expr()
            self.expect_op(")")
            return inner
        if tok.kind == "IDENT":
            self.advance()
            if self.at_op("("):
                return self.parse_call(tok.value)
            return ast.Column(tok.value)
        raise ParseError("unexpected %r" % (tok.value,), tok.pos)

    def parse_call(self, name):
        self.expect_op("(")
        name = name.upper()
        if self.at_op("*"):
            self.advance()
            self.expect_op(")")
            return ast.Call(name, [ast.Star()], False)
        distinct = self.accept_keyword("DISTINCT")
        args = []
        if not self.at_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return ast.Call(name, args, distinct)

    def parse_case(self):
        self.expect_keyword("CASE")
        whens = []
        while self.accept_keyword("WHEN"):
            cond = self.parse_expr()
            self.expect_keyword("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise ParseError("CASE needs a WHEN", self.tok.pos)
        default = self.parse_expr() if self.accept_keyword("ELSE") else None
        self.expect_keyword("END")
        return ast.Case(whens, default)


def parse(text):
    """Parse a single SELECT statement (an optional trailing ``;`` is not supported)."""
    return Parser(text).parse_select()
