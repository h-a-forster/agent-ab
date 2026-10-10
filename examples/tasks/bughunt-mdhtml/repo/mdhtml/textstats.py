"""Plain-text views of markdown: word counts, reading time, link lists."""

import re

from . import blocks as B
from .inline import plain_text

_LINK = re.compile(r'(?<!!)\[([^\]]+)\]\(\s*([^\s)]+)(?:\s+"[^"]*")?\s*\)')


def _block_text(node):
    if isinstance(node, (B.Heading, B.Paragraph)):
        return [plain_text(node.text)]
    if isinstance(node, B.CodeBlock):
        return []
    if isinstance(node, B.Quote):
        return [t for b in node.blocks for t in _block_text(b)]
    if isinstance(node, B.ListBlock):
        return [t for item in node.items for b in item for t in _block_text(b)]
    if isinstance(node, B.Table):
        cells = list(node.header)
        for row in node.rows:
            cells.extend(row)
        return [plain_text(c) for c in cells]
    return []


def to_plain_text(markdown):
    """Readable text of a document; code blocks are left out, blocks are separated by newlines."""
    return "\n".join(t for node in B.parse(markdown) for t in _block_text(node))


def word_count(markdown):
    return len(to_plain_text(markdown).split())


def reading_time(markdown, words_per_minute=200):
    """Whole minutes to read the document, never less than 1 for a non-empty text."""
    words = word_count(markdown)
    if words == 0:
        return 0
    return max(1, -(-words // words_per_minute))


def extract_links(markdown):
    """``[(text, url), ...]`` for every inline link (images are not links), in order."""
    return [(m.group(1), m.group(2)) for m in _LINK.finditer(markdown)]
