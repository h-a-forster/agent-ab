"""The public entry points."""

from . import blocks
from .frontmatter import split_frontmatter
from .render import Renderer
from .slug import Slugger
from .toc import outline, render_toc


class Document:
    """A rendered markdown document."""

    def __init__(self, html, headings, meta=None):
        self.html = html
        self.headings = headings
        self.meta = meta if meta is not None else {}

    def toc(self, min_depth=1, max_depth=3):
        return render_toc(self.headings, min_depth, max_depth)

    def outline(self, min_depth=1, max_depth=3):
        return outline(self.headings, min_depth, max_depth)

    def ids(self):
        return [h.id for h in self.headings]


def render_document(text, ids=True, frontmatter=False):
    """Render ``text``; with ``ids=False`` headings get no ``id`` attribute.

    With ``frontmatter=True`` a leading ``---`` metadata block is removed from the text and
    exposed as ``Document.meta``.
    """
    meta = {}
    if frontmatter:
        meta, text = split_frontmatter(text)
    renderer = Renderer(Slugger() if ids else None)
    html = renderer.render(blocks.parse(text))
    return Document(html, renderer.headings, meta)


def render(text):
    """Render markdown to an HTML string."""
    return render_document(text).html
