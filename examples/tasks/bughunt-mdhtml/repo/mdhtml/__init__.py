"""mdhtml: a small markdown-to-HTML renderer."""

from .document import Document, render, render_document
from .escape import escape_attr, escape_text
from .inline import render_inline
from .slug import Slugger, slugify

__all__ = ["render", "render_document", "Document", "render_inline", "slugify", "Slugger",
           "escape_text", "escape_attr"]
