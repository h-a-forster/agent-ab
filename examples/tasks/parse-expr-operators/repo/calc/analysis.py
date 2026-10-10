"""Static helpers over the AST."""

from __future__ import annotations

from .ast import Binary, Call, Num, Unary, Var


def free_vars(node) -> set[str]:
    """Names of all variables used in the expression."""
    if isinstance(node, Num):
        return set()
    if isinstance(node, Var):
        return {node.name}
    if isinstance(node, Unary):
        return free_vars(node.operand)
    if isinstance(node, Binary):
        return free_vars(node.left) | free_vars(node.right)
    if isinstance(node, Call):
        out: set[str] = set()
        for arg in node.args:
            out |= free_vars(arg)
        return out
    raise TypeError(f"unknown node {node!r}")


def node_count(node) -> int:
    """Total number of AST nodes."""
    if isinstance(node, (Num, Var)):
        return 1
    if isinstance(node, Unary):
        return 1 + node_count(node.operand)
    if isinstance(node, Binary):
        return 1 + node_count(node.left) + node_count(node.right)
    if isinstance(node, Call):
        return 1 + sum(node_count(a) for a in node.args)
    raise TypeError(f"unknown node {node!r}")
