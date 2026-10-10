"""Exceptions raised by sitegen."""


class SiteError(Exception):
    """Base class."""


class FrontMatterError(SiteError):
    """Malformed front matter."""


class TemplateError(SiteError):
    """A template cannot be parsed or rendered."""


class RouteError(SiteError):
    """A permalink pattern is invalid or two pages claim the same URL."""
