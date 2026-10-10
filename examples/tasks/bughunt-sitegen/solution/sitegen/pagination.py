"""Splitting a long list into pages with prev / next links."""

import math

from .util import join_url


class PageInfo:
    def __init__(self, number, total, items, url, prev_url, next_url):
        self.number = number
        self.total = total
        self.items = items
        self.url = url
        self.prev_url = prev_url
        self.next_url = next_url

    def __repr__(self):
        return "PageInfo(%d/%d, %d items, %s)" % (self.number, self.total, len(self.items), self.url)


def page_url(base_url, number):
    """First page lives at ``base_url`` itself, later ones at ``<base_url>page/<n>/``."""
    base = base_url if base_url.endswith("/") else base_url + "/"
    return base if number == 1 else join_url(base, "page", str(number)) + "/"


def paginate(items, per_page, base_url):
    """Split ``items`` into pages of ``per_page``.  An empty list still gives one (empty) page."""
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    items = list(items)
    total = max(1, math.ceil(len(items) / per_page))
    pages = []
    for number in range(1, total + 1):
        chunk = items[(number - 1) * per_page:number * per_page]
        prev_url = page_url(base_url, number - 1) if number > 1 else None
        next_url = page_url(base_url, number + 1) if number < total else None
        pages.append(PageInfo(number, total, chunk, page_url(base_url, number), prev_url, next_url))
    return pages
