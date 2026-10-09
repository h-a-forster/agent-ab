"""Normalisation of member paths for archives built and extracted on any OS."""

from __future__ import annotations

import os


class UnsafePathError(ValueError):
    """The path is absolute or escapes the archive root."""


def normalize(path: str) -> str:
    """Return the canonical form of an archive member path.

    The canonical form is relative, uses ``/`` as separator, and has no ``.``/``..`` parts,
    so it can be used as a dictionary key and compared across platforms.
    """
    if "\x00" in path:
        raise UnsafePathError(f"NUL byte in path: {path!r}")
    if os.path.isabs(path):
        raise UnsafePathError(f"absolute path: {path!r}")
    norm = os.path.normpath(path)
    if norm == ".":
        return ""
    if norm.startswith(".."):
        raise UnsafePathError(f"path escapes the archive root: {path!r}")
    return norm


def split_parts(path: str) -> list[str]:
    """The components of the normalised path (``[]`` for the root)."""
    norm = normalize(path)
    return norm.split(os.sep) if norm else []


def is_safe(path: str) -> bool:
    """True if ``path`` can be used as an archive member path."""
    try:
        normalize(path)
    except UnsafePathError:
        return False
    return True
