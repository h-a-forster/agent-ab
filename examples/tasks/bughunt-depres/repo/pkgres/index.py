"""An in-memory package index."""

from .errors import PkgresError
from .specifier import parse_range
from .version import Version


class Release:
    """One published version of a package and its dependency ranges."""

    def __init__(self, name, version, deps):
        self.name = name
        self.version = version
        self.deps = deps  # {dependency name: Range}

    def __repr__(self):
        return "Release(%s@%s)" % (self.name, self.version)


class PackageIndex:
    def __init__(self):
        self._releases = {}

    def add(self, name, version, deps=None):
        v = Version.parse(version)
        parsed = {dep: parse_range(rng) for dep, rng in (deps or {}).items()}
        bucket = self._releases.setdefault(name, {})
        key = (v.core, v.pre)
        if key in bucket:
            raise PkgresError("%s@%s already in the index" % (name, v))
        bucket[key] = Release(name, v, parsed)
        return bucket[key]

    @classmethod
    def from_dict(cls, data):
        """``{"name": {"1.0.0": {"dep": "^1.0"}, ...}, ...}``"""
        index = cls()
        for name in sorted(data):
            for version, deps in data[name].items():
                index.add(name, version, deps)
        return index

    def names(self):
        return sorted(self._releases)

    def __contains__(self, name):
        return name in self._releases

    def releases(self, name):
        """All releases of ``name``, highest version first."""
        found = self._releases.get(name, {})
        return sorted(found.values(), key=lambda r: r.version, reverse=True)

    def versions(self, name):
        return [r.version for r in self.releases(name)]

    def release(self, name, version):
        v = Version.parse(version)
        try:
            return self._releases[name][(v.core, v.pre)]
        except KeyError:
            raise PkgresError("no release %s@%s" % (name, v)) from None

    def candidates(self, name, ranges):
        """Releases of ``name`` (highest first) matching every range in ``ranges``."""
        releases = self.releases(name)
        for rng in ranges:
            allowed = set(rng.filter([r.version for r in releases]))
            releases = [r for r in releases if r.version in allowed]
        return releases
