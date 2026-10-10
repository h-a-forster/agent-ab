"""Permalinks: which URL does a page get?"""

from .errors import RouteError
from .util import ensure_slashes, slugify

DEFAULT_PATTERN = "/{slug}/"
KNOWN = {"slug", "year", "month", "day", "section", "title"}


def _fields(page):
    date = page.date
    return {
        "slug": page.slug,
        "year": "%04d" % date.year if date else "",
        "month": "%02d" % date.month if date else "",
        "day": "%02d" % date.day if date else "",
        "section": page.section,
        "title": slugify(page.title),
    }


def validate_pattern(pattern):
    import string

    for _, field, _, _ in string.Formatter().parse(pattern):
        if field is not None and field not in KNOWN:
            raise RouteError("unknown placeholder {%s} in %r" % (field, pattern))


def permalink(page, patterns):
    """URL of a page.

    Order of precedence: ``url:`` in the front matter (used verbatim apart from the slashes),
    ``permalink:`` pattern in the front matter, an ``index.md`` file (its directory), the
    pattern configured for the page's section, the ``default`` pattern, ``/{slug}/``.
    Dated placeholders need a date: month and day are zero padded (``2024/03/05``).
    """
    explicit = page.meta.get("url")
    if explicit:
        return ensure_slashes(str(explicit)) if not str(explicit).endswith((".html", ".xml")) else "/" + str(explicit).lstrip("/")
    pattern = page.meta.get("permalink")
    if not pattern and page.is_index:
        return ensure_slashes(page.directory) if page.directory else "/"
    if not pattern:
        pattern = patterns.get(page.section) or patterns.get("default") or DEFAULT_PATTERN
    validate_pattern(pattern)
    fields = _fields(page)
    needs_date = any(name in pattern for name in ("{year}", "{month}", "{day}"))
    if needs_date and page.date is None:
        raise RouteError("%s: pattern %r needs a date" % (page.source, pattern))
    return ensure_slashes(pattern.format(**fields))


def assign_urls(pages, patterns):
    """Set ``page.url`` on every page; two pages with the same URL are an error."""
    seen = {}
    for page in pages:
        page.url = permalink(page, patterns)
        if page.url in seen:
            raise RouteError("%s and %s both map to %s" % (seen[page.url], page.source, page.url))
        seen[page.url] = page.source
    return pages
