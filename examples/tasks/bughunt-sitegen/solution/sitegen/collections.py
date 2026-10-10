"""Groups of pages: by section, tag or year."""


def sort_newest_first(pages):
    """Newest date first; pages with the same date are ordered by title (A to Z); undated pages
    come last, also ordered by title."""
    dated = [p for p in pages if p.date is not None]
    undated = [p for p in pages if p.date is None]
    dated.sort(key=lambda p: p.title.lower())
    dated.sort(key=lambda p: p.date, reverse=True)
    undated.sort(key=lambda p: p.title.lower())
    return dated + undated


def by_section(pages, section):
    return sort_newest_first([p for p in pages if p.section == section])


def by_tag(pages):
    """``{tag: pages}`` (tags compared case-insensitively, shown as first spelling), each list newest first."""
    groups = {}
    names = {}
    for page in pages:
        for tag in page.tags:
            key = tag.lower()
            names.setdefault(key, tag)
            groups.setdefault(key, []).append(page)
    return {names[k]: sort_newest_first(v) for k, v in sorted(groups.items())}


def by_year(pages):
    """``{year: pages}`` newest year first, pages newest first; undated pages are skipped."""
    groups = {}
    for page in pages:
        if page.date is not None:
            groups.setdefault(page.date.year, []).append(page)
    return {year: sort_newest_first(groups[year]) for year in sorted(groups, reverse=True)}


def neighbours(ordered, page):
    """``(newer, older)`` pages next to ``page`` in a newest-first list (either may be None)."""
    index = ordered.index(page)
    newer = ordered[index - 1] if index > 0 else None
    older = ordered[index + 1] if index + 1 < len(ordered) else None
    return newer, older
