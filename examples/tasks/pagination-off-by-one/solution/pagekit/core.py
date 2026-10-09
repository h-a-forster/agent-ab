"""Core pagination logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Sequence, TypeVar

T = TypeVar("T")


class PageOutOfRange(LookupError):
    """Raised when a page number outside 1..total_pages is requested."""


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    number: int
    per_page: int
    total_items: int
    total_pages: int

    @property
    def has_prev(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.total_pages


def paginate(items: Sequence[T], page: int, per_page: int = 20) -> Page[T]:
    """Return page number ``page`` (1-based) of ``items``."""
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    total_items = len(items)
    total_pages = max(1, -(-total_items // per_page))
    if page < 1 or page > total_pages:
        raise PageOutOfRange(f"page {page} is outside 1..{total_pages}")
    start = (page - 1) * per_page
    end = start + per_page
    return Page(
        items=list(items[start:end]),
        number=page,
        per_page=per_page,
        total_items=total_items,
        total_pages=total_pages,
    )


def page_numbers(current: int, total_pages: int, window: int = 2) -> list[int]:
    """Page numbers to show in a pager: ``window`` pages either side of ``current``."""
    if total_pages < 1:
        return []
    first = max(1, current - window)
    last = min(total_pages, current + window)
    return list(range(first, last + 1))
