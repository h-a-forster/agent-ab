"""Normalisation of member paths for archives built and extracted on any OS."""

from __future__ import annotations

import re

# Pure string handling on purpose: os.path differs between platforms, and archives move
# between them.
_SEPARATORS = re.compile(r"[\\/]")
_DRIVE = re.compile(r"[A-Za-z]:")


class UnsafePathError(ValueError):
    """The path is absolute or escapes the archive root."""


def _components(path: str) -> list[str]:
    if "\x00" in path:
        raise UnsafePathError(f"NUL byte in path: {path!r}")
    if path[:1] in ("/", "\\"):
        raise UnsafePathError(f"absolute path: {path!r}")
    if _DRIVE.match(path):
        raise UnsafePathError(f"path with a drive letter: {path!r}")
    parts: list[str] = []
    for part in _SEPARATORS.split(path):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise UnsafePathError(f"path escapes the archive root: {path!r}")
            parts.pop()
        else:
            parts.append(part)
    return parts


def normalize(path: str) -> str:
    """Return the canonical form of an archive member path.

    The canonical form is relative, uses ``/`` as separator, and has no ``.``/``..`` parts,
    so it can be used as a dictionary key and compared across platforms.
    """
    return "/".join(_components(path))


def split_parts(path: str) -> list[str]:
    """The components of the normalised path (``[]`` for the root)."""
    return _components(path)


def is_safe(path: str) -> bool:
    """True if ``path`` can be used as an archive member path."""
    try:
        _components(path)
    except UnsafePathError:
        return False
    return True
