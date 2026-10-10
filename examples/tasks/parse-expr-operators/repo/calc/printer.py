"""Print an AST back to source with minimal parentheses."""

from __future__ import annotations

from .ast import Binary, Call, Num, Unary, Var

_PREC = {"+": 1, "-": 1, "*": 2, "/": 2}
_UNARY_PREC = 3
_ATOM_PREC = 4


def _prec(node) -> int:
    if isinstance(node, Binary):
        return _PREC[node.op]
    if isinstance(node, Unary):
        return _UNARY_PREC
    return _ATOM_PREC


def _wrap(node, needs_parens: bool) -> str:
    text = to_source(node)
    return f"({text})" if needs_parens else text


def to_source(node) -> str:
    if isinstance(node, Num):
        return repr(node.value)
    if isinstance(node, Var):
        return node.name
    if isinstance(node, Unary):
        return node.op + _wrap(node.operand, _prec(node.operand) < _UNARY_PREC)
    if isinstance(node, Binary):
        p = _PREC[node.op]
        left = _wrap(node.left, _prec(node.left) < p)
        right = _wrap(node.right, _prec(node.right) <= p)
        return f"{left} {node.op} {right}"
    if isinstance(node, Call):
        return f"{node.name}({', '.join(to_source(a) for a in node.args)})"
    raise TypeError(f"cannot print {node!r}")
