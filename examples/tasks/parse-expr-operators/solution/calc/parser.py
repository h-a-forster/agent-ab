"""Recursive-descent parser."""

from __future__ import annotations

from .ast import Binary, Call, Num, Ternary, Unary, Var
from .errors import ParseError
from .lexer import Token, tokenize


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = tokenize(text)
        self.i = 0

    def peek(self) -> Token:
        return self.tokens[self.i]

    def next(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def at_op(self, *ops: str) -> bool:
        tok = self.peek()
        return tok.kind == "op" and tok.text in ops

    def expect(self, op: str) -> None:
        tok = self.next()
        if tok.kind != "op" or tok.text != op:
            raise ParseError(f"expected {op!r}", tok.pos)

    def parse(self):
        node = self.ternary()
        tok = self.peek()
        if tok.kind != "end":
            raise ParseError(f"unexpected {tok.text!r}", tok.pos)
        return node

    def ternary(self):
        cond = self.logical_or()
        if self.at_op("?"):
            self.next()
            then = self.ternary()
            self.expect(":")
            return Ternary(cond, then, self.ternary())
        return cond

    def logical_or(self):
        left = self.logical_and()
        while self.at_op("||"):
            self.next()
            left = Binary("||", left, self.logical_and())
        return left

    def logical_and(self):
        left = self.comparison()
        while self.at_op("&&"):
            self.next()
            left = Binary("&&", left, self.comparison())
        return left

    def comparison(self):
        left = self.additive()
        if self.at_op("<", "<=", ">", ">=", "==", "!="):
            op = self.next().text
            left = Binary(op, left, self.additive())
            if self.at_op("<", "<=", ">", ">=", "==", "!="):
                tok = self.peek()
                raise ParseError("comparison operators do not chain", tok.pos)
        return left

    def additive(self):
        left = self.term()
        while self.at_op("+", "-"):
            op = self.next().text
            left = Binary(op, left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.at_op("*", "/", "%"):
            op = self.next().text
            left = Binary(op, left, self.unary())
        return left

    def unary(self):
        if self.at_op("+", "-", "!"):
            op = self.next().text
            return Unary(op, self.unary())
        return self.power()

    def power(self):
        base = self.primary()
        if self.at_op("**"):
            self.next()
            return Binary("**", base, self.unary())
        return base

    def primary(self):
        tok = self.next()
        if tok.kind == "num":
            text = tok.text
            return Num(float(text) if "." in text else int(text))
        if tok.kind == "name":
            if self.at_op("("):
                self.next()
                args = []
                if not self.at_op(")"):
                    args.append(self.ternary())
                    while self.at_op(","):
                        self.next()
                        args.append(self.ternary())
                self.expect(")")
                return Call(tok.text, tuple(args))
            return Var(tok.text)
        if tok.kind == "op" and tok.text == "(":
            node = self.ternary()
            self.expect(")")
            return node
        raise ParseError(f"unexpected {tok.text or 'end of input'!r}", tok.pos)


def parse(text: str):
    return _Parser(text).parse()
