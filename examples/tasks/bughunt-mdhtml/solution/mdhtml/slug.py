"""Heading ids ("slugs") that are unique within one document."""

import re

_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)
_SPACES = re.compile(r"[\s_-]+", re.UNICODE)


def slugify(text):
    """Lower-case, drop punctuation, join words with single hyphens.

    ``"Hello, World!"`` -> ``"hello-world"``.  Text with no letters or digits gives
    ``"section"``.
    """
    cleaned = _STRIP.sub("", text.strip().lower())
    slug = _SPACES.sub("-", cleaned).strip("-")
    return slug or "section"


class Slugger:
    """Hands out unique ids for one document.

    The first ``Intro`` is ``intro``, the next ``intro-1``, then ``intro-2``.  A generated
    id never collides with an id handed out earlier, even if a later heading literally slugifies
    to it.  Every new ``Slugger`` starts empty.
    """

    def __init__(self):
        self._used = set()
        self._counts = {}

    def slug(self, text):
        base = slugify(text)
        candidate = base
        n = self._counts.get(base, 0)
        while candidate in self._used:
            n += 1
            candidate = "%s-%d" % (base, n)
        self._counts[base] = n
        self._used.add(candidate)
        return candidate

    def used(self):
        return sorted(self._used)
