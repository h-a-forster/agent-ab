"""Pages: source files turned into objects with a date, slug and metadata."""

import datetime
import posixpath
import re

from . import frontmatter
from .errors import SiteError
from .util import slugify

_DATE_PREFIX = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)$")


class Page:
    def __init__(self, source, meta, body):
        self.source = source
        self.meta = meta
        self.body = body
        directory, filename = posixpath.split(source)
        stem = posixpath.splitext(filename)[0]
        self.directory = directory
        self.section = directory.split("/")[0] if directory else ""
        file_date = None
        m = _DATE_PREFIX.match(stem)
        if m:
            try:
                file_date = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                stem = m.group(4)
            except ValueError:
                file_date = None
        self.stem = stem
        meta_date = meta.get("date")
        if isinstance(meta_date, datetime.datetime):
            meta_date = meta_date.date()
        if meta_date is not None and not isinstance(meta_date, datetime.date):
            raise SiteError("%s: 'date' must be YYYY-MM-DD" % source)
        self.date = meta_date or file_date
        self.slug = slugify(str(meta["slug"])) if meta.get("slug") else slugify(stem) or "page"
        self.title = str(meta["title"]) if meta.get("title") else stem.replace("-", " ").replace("_", " ").title()
        self.draft = bool(meta.get("draft", False))
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        self.tags = [str(t) for t in tags]
        self.layout = str(meta.get("layout", "default"))
        self.url = None
        self.html = None

    @property
    def is_index(self):
        return self.stem == "index"

    def __repr__(self):
        return "Page(%s)" % self.source


def load_pages(files):
    """Pages for every ``.md`` file in a ``{path: text}`` mapping, sorted by source path."""
    pages = []
    for path in sorted(files):
        if not path.endswith(".md"):
            continue
        meta, body = frontmatter.split(files[path])
        pages.append(Page(path, meta, body))
    return pages
