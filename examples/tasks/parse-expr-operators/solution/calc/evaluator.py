"""Tree-walking evaluator."""

from __future__ import annotations

import math

from .ast import Binary, Call, Num, Ternary, Unary, Var
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


def _binary(op, left, right):
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise EvalError("division by zero")
        return left / right
    if op == "%":
        if right == 0:
            raise EvalError("modulo by zero")
        return left % right
    if op == "**":
        if left == 0 and right < 0:
            raise EvalError("zero to a negative power")
        result = left**right
        if isinstance(result, complex):
            raise EvalError("complex result")
        return result
    if op == "<":
        return int(left < right)
    if op == "<=":
        return int(left <= right)
    if op == ">":
        return int(left > right)
    if op == ">=":
        return int(left >= right)
    if op == "==":
        return int(left == right)
    if op == "!=":
        return int(left != right)
    raise TypeError(f"unknown operator {op}")


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
        if node.op == "!":
            return 0 if value else 1
        return -value if node.op == "-" else +value
    if isinstance(node, Ternary):
        return evaluate(node.then if evaluate(node.cond, env) else node.orelse, env)
    if isinstance(node, Binary):
        if node.op == "&&":
            return 1 if evaluate(node.left, env) and evaluate(node.right, env) else 0
        if node.op == "||":
            return 1 if evaluate(node.left, env) or evaluate(node.right, env) else 0
        left = evaluate(node.left, env)
        right = evaluate(node.right, env)
        return _binary(node.op, left, right)
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
