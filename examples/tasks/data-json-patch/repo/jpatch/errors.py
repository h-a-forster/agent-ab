"""Error types."""

from __future__ import annotations


class PointerError(ValueError):
    """A JSON Pointer is malformed or does not resolve."""


class PatchError(ValueError):
    """A patch could not be applied. ``index`` is the operation number (``None`` if general)."""

    def __init__(self, index: int | None, message: str) -> None:
        super().__init__(message if index is None else f"operation {index}: {message}")
        self.index = index
        self.message = message
