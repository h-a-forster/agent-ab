"""Error types."""

from __future__ import annotations


class ParseError(ValueError):
    """Bad syntax. ``pos`` is the 0-based offset of the offending token."""

    def __init__(self, message: str, pos: int) -> None:
        super().__init__(f"{message} at {pos}")
        self.pos = pos


class EvalError(ArithmeticError):
    """An expression could not be evaluated."""
