"""Lockfile text format: one ``name@version`` per line, sorted by name."""

from .errors import LockfileError, VersionError
from .resolver import Resolution
from .version import Version

HEADER = "# pkgres lockfile v1"


def dump(resolution):
    lines = [HEADER]
    for name, version in resolution.items():
        lines.append("%s@%s" % (name, version))
    return "\n".join(lines) + "\n"


def load(text):
    chosen = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, version = line.rpartition("@")
        if not sep or not name:
            raise LockfileError("line %d: expected name@version" % number)
        try:
            chosen[name] = Version.parse(version)
        except VersionError:
            raise LockfileError("line %d: bad version %r" % (number, version)) from None
    return Resolution(chosen)
