"""Tree-walking evaluator."""

from __future__ import annotations

import math

from .ast import Binary, Call, Num, Unary, Var
from .errors import EvalError
from .parser import parse

FUNCTIONS = {
    "abs": (1, abs),
    "min": (None, min),
    "max": (None, max),
    "sqrt": (1, lambda x: math.sqrt(x) if x >= 0 else _fail("sqrt of a negative number")),
}


def _fail(message: str):
    raise EvalError(message)


def evaluate(node, env=None):
    env = env or {}
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Var):
        if node.name not in env:
            raise EvalError(f"undefined variable {node.name}")
        return env[node.name]
    if isinstance(node, Unary):
        value = evaluate(node.operand, env)
        return -value if node.op == "-" else +value
    if isinstance(node, Binary):
        left = evaluate(node.left, env)
        right = evaluate(node.right, env)
        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                raise EvalError("division by zero")
            return left / right
    if isinstance(node, Call):
        if node.name not in FUNCTIONS:
            raise EvalError(f"unknown function {node.name}")
        arity, fn = FUNCTIONS[node.name]
        args = [evaluate(a, env) for a in node.args]
        if (arity is not None and len(args) != arity) or (arity is None and not args):
            raise EvalError(f"wrong number of arguments for {node.name}")
        return fn(*args)
    raise TypeError(f"cannot evaluate {node!r}")


def eval_expr(text: str, env=None):
    return evaluate(parse(text), env)
