"""Inline markdown: code spans, links, images, emphasis, line breaks."""

import re

from .escape import escape_attr, escape_code, escape_text

_CODE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
_ESCAPABLE = "\\`*_{}[]()#+-.!|~<>"
_ESCAPE = re.compile(r"\\([%s])" % re.escape(_ESCAPABLE))
_AUTOLINK = re.compile(r"<((?:https?|ftp)://[^\s<>]+)>")
_IMAGE = re.compile(r'!\[([^\]]*)\]\(\s*([^\s)]+)(?:\s+"([^"]*)")?\s*\)')
_LINK = re.compile(r'\[([^\]]+)\]\(\s*([^\s)]+)(?:\s+"([^"]*)")?\s*\)')
_STRONG = re.compile(r"(\*\*|(?<![A-Za-z0-9])__)(?=\S)(.+?)(?<=\S)\1(?![A-Za-z0-9])" , re.DOTALL)
_EM = re.compile(r"(?<![*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)|(?<![A-Za-z0-9_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![A-Za-z0-9_])", re.DOTALL)
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_HARD_BREAK = re.compile(r" {2,}\n")
_HOLDER = re.compile("\x00(\\d+)\x00")


class _Atoms:
    """Pieces of finished HTML that must not be touched by later passes."""

    def __init__(self):
        self.items = []

    def hold(self, html):
        self.items.append(html)
        return "\x00%d\x00" % (len(self.items) - 1)

    def restore(self, text):
        # Held atoms may themselves contain holders (a link around a code span).
        while _HOLDER.search(text):
            text = _HOLDER.sub(lambda m: self.items[int(m.group(1))], text)
        return text


def render_inline(text):
    """Convert one run of inline markdown to HTML."""
    return _render(text, _Atoms())


def _render(text, atoms):
    text = _CODE.sub(lambda m: atoms.hold(_code_span(m.group(2))), text)
    text = _ESCAPE.sub(lambda m: atoms.hold(escape_text(m.group(1))), text)
    text = _IMAGE.sub(lambda m: atoms.hold(_image(m)), text)
    text = _LINK.sub(lambda m: atoms.hold(_link(m, atoms)), text)
    text = _AUTOLINK.sub(lambda m: atoms.hold(_autolink(m.group(1))), text)
    text = escape_text(text)
    text = atoms.restore(text)
    text = _emphasis(text)
    text = _HARD_BREAK.sub("<br>\n", text)
    return text


def _code_span(content):
    content = content.replace("\n", " ")
    if len(content) > 2 and content[0] == " " and content[-1] == " " and content.strip():
        content = content[1:-1]
    return "<code>%s</code>" % escape_code(content)


def _emphasis(text):
    text = _STRONG.sub(lambda m: "<strong>%s</strong>" % m.group(2), text)
    text = _EM.sub(lambda m: "<em>%s</em>" % (m.group(1) if m.group(1) is not None else m.group(2)), text)
    text = _STRIKE.sub(lambda m: "<del>%s</del>" % m.group(1), text)
    return text


def _title_attr(title):
    return "" if title is None else ' title="%s"' % escape_attr(title)


def _link(m, atoms):
    label, url, title = m.group(1), m.group(2), m.group(3)
    inner = _render(label, atoms)
    return '<a href="%s"%s>%s</a>' % (escape_text(url), _title_attr(title), inner)


def _image(m):
    alt, url, title = m.group(1), m.group(2), m.group(3)
    return '<img src="%s" alt="%s"%s>' % (escape_text(url), escape_text(alt), _title_attr(title))


def _autolink(url):
    return '<a href="%s">%s</a>' % (escape_text(url), escape_text(url))


def plain_text(text):
    """The text of an inline run with all markdown syntax removed (used for ids)."""
    text = _CODE.sub(lambda m: m.group(2), text)
    text = _IMAGE.sub(lambda m: m.group(1), text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _AUTOLINK.sub(lambda m: m.group(1), text)
    text = _ESCAPE.sub(lambda m: m.group(1), text)
    text = _STRONG.sub(lambda m: m.group(2), text)
    text = _EM.sub(lambda m: m.group(1) if m.group(1) is not None else m.group(2), text)
    text = _STRIKE.sub(lambda m: m.group(1), text)
    return text.strip()
