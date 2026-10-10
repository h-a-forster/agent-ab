"""AST node classes (immutable, comparable)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Num:
    value: int | float


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: object


@dataclass(frozen=True)
class Binary:
    op: str
    left: object
    right: object


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple


@dataclass(frozen=True)
class Ternary:
    cond: object
    then: object
    orelse: object
