"""Exceptions raised by pkgres."""


class PkgresError(Exception):
    """Base class."""


class VersionError(PkgresError, ValueError):
    """A version string is not valid semver."""


class SpecError(PkgresError, ValueError):
    """A version range / requirement string cannot be parsed."""


class ResolutionError(PkgresError):
    """No set of versions satisfies all requirements."""

    def __init__(self, message, name=None):
        super().__init__(message)
        self.name = name


class CycleError(PkgresError):
    """The dependency graph has a cycle; ``cycle`` lists the package names on it."""

    def __init__(self, cycle):
        super().__init__("dependency cycle: " + " -> ".join(cycle))
        self.cycle = list(cycle)


class LockfileError(PkgresError):
    """A lockfile line is malformed."""
