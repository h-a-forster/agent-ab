"""Parsing of command-line style requirements such as ``left-pad@^1.2`` or ``@org/lib``."""

from .errors import SpecError
from .specifier import parse_range


def parse_requirement(text):
    """``"name"``, ``"name@range"`` or a scoped ``"@scope/name[@range]"`` -> ``(name, Range)``."""
    text = text.strip()
    if not text:
        raise SpecError("empty requirement")
    name, sep, rng = text.partition("@")
    if not sep:
        rng = "*"
    if not name or name == "@":
        raise SpecError("missing package name in %r" % text)
    return name, parse_range(rng)


def parse_requirements(items):
    """Several requirement strings -> ``{name: Range}``; the same name twice is an error."""
    out = {}
    for item in items:
        name, rng = parse_requirement(item)
        if name in out:
            raise SpecError("%s required twice" % name)
        out[name] = rng
    return out
