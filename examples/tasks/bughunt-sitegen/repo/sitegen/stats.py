"""Statistics about a built site."""

import re

from . import collections as C

_WORDS = re.compile(r"[A-Za-z0-9']+")


def word_count(text):
    return len(_WORDS.findall(text))


def reading_minutes(text, wpm=200):
    """Whole minutes (rounded up, at least 1 for non-empty text, 0 for empty)."""
    words = word_count(text)
    if words == 0:
        return 0
    return max(1, -(-words // wpm))


def tag_counts(pages):
    """``[(tag, count)]`` most used first, ties alphabetical."""
    counts = {tag: len(items) for tag, items in C.by_tag(pages).items()}
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))


def posts_per_year(pages):
    return {year: len(items) for year, items in C.by_year(pages).items()}


def summary(site):
    published = site.published()
    return {
        "pages": len(site.pages),
        "published": len(published),
        "drafts": len(site.pages) - len(published) if not site.config["include_drafts"] else 0,
        "tags": len(C.by_tag(published)),
        "words": sum(word_count(p.body) for p in published),
        "broken_links": len(site.broken_links),
    }
