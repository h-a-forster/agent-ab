"""Version ranges: ``^1.2.3``, ``~1.2``, ``>=1 <2``, ``1.x``, ``1.2.3 - 2.0.0``, ``a || b``."""

import re

from .errors import SpecError
from .version import Version

_OPS = ("<=", ">=", "<", ">", "=")
_PARTIAL = re.compile(
    r"^v?(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?$"
)
_SPACE_AFTER_OP = re.compile(r"(<=|>=|<|>|=|\^|~)\s+")
_HYPHEN = re.compile(r"^(\S+)\s+-\s+(\S+)$")

ZERO = Version(0, 0, 0)


class Comparator:
    """One ``<op> version`` test."""

    __slots__ = ("op", "version")

    def __init__(self, op, version):
        self.op = op
        self.version = version

    def matches(self, v):
        if self.op == "=":
            return v == self.version
        if self.op == "<":
            return v < self.version
        if self.op == "<=":
            return v <= self.version
        if self.op == ">":
            return v > self.version
        return v >= self.version

    def __repr__(self):
        return "%s%s" % (self.op, self.version)


class ComparatorSet:
    """Comparators that must all hold (an AND group)."""

    def __init__(self, comparators):
        self.comparators = list(comparators)

    def matches(self, v):
        """All comparators hold; a prerelease only matches if the set mentions a prerelease
        of the same ``major.minor.patch`` (so ``>=1.0.0`` never selects ``2.0.0-beta``)."""
        if not all(c.matches(v) for c in self.comparators):
            return False
        if v.pre:
            return any(c.version.pre and c.version.same_core(v) for c in self.comparators)
        return True

    def __repr__(self):
        return " ".join(repr(c) for c in self.comparators)


class Range:
    """A union (``||``) of comparator sets."""

    def __init__(self, sets, text="*"):
        self.sets = list(sets)
        self.text = text

    def matches(self, version):
        v = Version.parse(version)
        return any(s.matches(v) for s in self.sets)

    def filter(self, versions):
        """The versions that match, in the given order."""
        parsed = [Version.parse(v) for v in versions]
        return [v for v in parsed if any(all(c.matches(v) for c in s.comparators) for s in self.sets)]

    def __repr__(self):
        return "Range(%r)" % self.text

    def __str__(self):
        return self.text


def parse_range(text):
    if isinstance(text, Range):
        return text
    if not isinstance(text, str):
        raise SpecError("range must be a string, got %r" % (text,))
    sets = []
    for part in text.split("||"):
        sets.append(ComparatorSet(_parse_set(part.strip())))
    return Range(sets, text.strip() or "*")


def _parse_partial(token):
    """-> ``(numbers, pre)``; numbers stops at the first wildcard (so ``1.x`` is ``[1]``)."""
    m = _PARTIAL.match(token)
    if not m:
        raise SpecError("invalid version in range: %r" % token)
    numbers = []
    for group in m.groups()[:3]:
        if group is None or group in "xX*":
            break
        numbers.append(int(group))
    if not numbers and m.group(1) not in ("x", "X", "*"):
        raise SpecError("invalid version in range: %r" % token)
    pre = tuple(int(p) if p.isdigit() else p for p in m.group(4).split(".")) if m.group(4) else ()
    if pre and len(numbers) < 3:
        raise SpecError("prerelease needs a full version: %r" % token)
    return numbers, pre


def _fill(numbers, pre=()):
    nums = list(numbers) + [0] * (3 - len(numbers))
    return Version(nums[0], nums[1], nums[2], pre)


def next_after_prefix(numbers):
    """The smallest version that no longer starts with the given 1-3 numbers."""
    if len(numbers) == 1:
        return Version(numbers[0], 1, 0)
    if len(numbers) == 2:
        return Version(numbers[0], numbers[1] + 1, 0)
    return Version(numbers[0], numbers[1], numbers[2] + 1)


def _caret_upper(numbers):
    """Upper bound of ``^numbers``: bump the left-most non-zero number."""
    if numbers[0] != 0:
        return Version(numbers[0] + 1, 0, 0)
    return next_after_prefix(numbers)


def _parse_set(text):
    if not text:
        return [Comparator(">=", ZERO)]
    hyphen = _HYPHEN.match(text)
    if hyphen:
        return _hyphen(hyphen.group(1), hyphen.group(2))
    comparators = []
    for token in _SPACE_AFTER_OP.sub(r"\1", text).split():
        comparators.extend(_expand(token))
    return comparators


def _hyphen(low, high):
    low_nums, low_pre = _parse_partial(low)
    high_nums, high_pre = _parse_partial(high)
    out = [Comparator(">=", _fill(low_nums, low_pre))]
    if len(high_nums) == 3:
        out.append(Comparator("<=", _fill(high_nums, high_pre)))
    elif high_nums:
        out.append(Comparator("<", next_after_prefix(high_nums)))
    return out


def _expand(token):
    if token in ("*", "x", "X"):
        return [Comparator(">=", ZERO)]
    if token[0] == "^":
        numbers, pre = _parse_partial(token[1:])
        if not numbers:
            return [Comparator(">=", ZERO)]
        return [Comparator(">=", _fill(numbers, pre)), Comparator("<", _caret_upper(numbers))]
    if token[0] == "~":
        numbers, pre = _parse_partial(token[1:])
        if not numbers:
            return [Comparator(">=", ZERO)]
        prefix = numbers[:2] if len(numbers) >= 2 else numbers
        return [Comparator(">=", _fill(numbers, pre)), Comparator("<", next_after_prefix(prefix))]
    op = "="
    for candidate in _OPS:
        if token.startswith(candidate):
            op = candidate
            token = token[len(candidate):]
            break
    numbers, pre = _parse_partial(token)
    if not numbers:
        if op in ("<", ">"):
            return [Comparator("<", ZERO)]  # nothing is below/above "any"
        return [Comparator(">=", ZERO)]
    full = len(numbers) == 3
    if op == "=":
        if full:
            return [Comparator("=", _fill(numbers, pre))]
        return [Comparator(">=", _fill(numbers)), Comparator("<", next_after_prefix(numbers))]
    if op == ">":
        return [Comparator(">", _fill(numbers, pre))] if full else [Comparator(">=", next_after_prefix(numbers))]
    if op == ">=":
        return [Comparator(">=", _fill(numbers, pre))]
    if op == "<":
        return [Comparator("<", _fill(numbers, pre))]
    return [Comparator("<=", _fill(numbers, pre))] if full else [Comparator("<", next_after_prefix(numbers))]


def satisfies(version, range_text):
    return parse_range(range_text).matches(version)


def max_satisfying(versions, range_text):
    """The highest matching version or ``None``."""
    found = parse_range(range_text).filter(versions)
    return max(found) if found else None


def min_satisfying(versions, range_text):
    found = parse_range(range_text).filter(versions)
    return min(found) if found else None
