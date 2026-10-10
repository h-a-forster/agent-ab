"""Semantic versions (semver 2.0): parsing, precedence and bumping."""

import re
from functools import total_ordering

from .errors import VersionError

_SEMVER = re.compile(
    r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _compare_identifiers(a, b):
    """Compare two prerelease identifier tuples by semver rules; returns -1, 0 or 1."""
    for x, y in zip(a, b):
        if x == y:
            continue
        x_num, y_num = isinstance(x, int), isinstance(y, int)
        if x_num and y_num:
            return -1 if x < y else 1
        if x_num:
            return -1  # numeric identifiers sort before alphanumeric ones
        if y_num:
            return 1
        return -1 if x < y else 1
    return (len(a) > len(b)) - (len(a) < len(b))


@total_ordering
class Version:
    """An immutable semantic version.

    Precedence ignores build metadata (``1.0.0+a == 1.0.0+b``); a prerelease sorts before
    its release (``1.0.0-rc.1 < 1.0.0``).  Numeric prerelease identifiers compare as numbers,
    so ``1.0.0-alpha.2 < 1.0.0-alpha.10``.
    """

    __slots__ = ("major", "minor", "patch", "pre", "build")

    def __init__(self, major, minor, patch, pre=(), build=()):
        object.__setattr__(self, "major", major)
        object.__setattr__(self, "minor", minor)
        object.__setattr__(self, "patch", patch)
        object.__setattr__(self, "pre", tuple(pre))
        object.__setattr__(self, "build", tuple(build))

    def __setattr__(self, name, value):
        raise AttributeError("Version is immutable")

    @classmethod
    def parse(cls, text):
        if isinstance(text, Version):
            return text
        m = _SEMVER.match(text.strip()) if isinstance(text, str) else None
        if not m:
            raise VersionError("invalid version %r" % (text,))
        pre = ()
        if m.group(4):
            pre = tuple(int(p) if p.isdigit() else p for p in m.group(4).split("."))
        build = tuple(m.group(5).split(".")) if m.group(5) else ()
        return cls(int(m.group(1)), int(m.group(2)), int(m.group(3)), pre, build)

    @property
    def core(self):
        return (self.major, self.minor, self.patch)

    def same_core(self, other):
        return self.core == other.core

    def is_prerelease(self):
        return bool(self.pre)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self.core == other.core and _compare_identifiers(self.pre, other.pre) == 0 \
            and bool(self.pre) == bool(other.pre)

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        if self.core != other.core:
            return self.core < other.core
        if not self.pre and not other.pre:
            return False
        if not self.pre:
            return False
        if not other.pre:
            return True
        return _compare_identifiers(self.pre, other.pre) < 0

    def __hash__(self):
        return hash((self.core, self.pre))

    def identical(self, other):
        return self == other and self.build == other.build

    def bump(self, part):
        if part == "major":
            return Version(self.major + 1, 0, 0)
        if part == "minor":
            return Version(self.major, self.minor + 1, 0)
        if part == "patch":
            return Version(self.major, self.minor, self.patch + 1)
        raise ValueError("unknown part %r" % (part,))

    def __str__(self):
        text = "%d.%d.%d" % self.core
        if self.pre:
            text += "-" + ".".join(str(p) for p in self.pre)
        if self.build:
            text += "+" + ".".join(self.build)
        return text

    def __repr__(self):
        return "Version(%r)" % str(self)


def sort_versions(versions, reverse=False):
    return sorted((Version.parse(v) for v in versions), reverse=reverse)
