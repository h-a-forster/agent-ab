"""Block nodes -> HTML text."""

from . import blocks as B
from .escape import escape_attr, escape_code
from .inline import plain_text, render_inline


class HeadingInfo:
    """What the table of contents needs to know about a heading."""

    def __init__(self, level, text, html, id):
        self.level = level
        self.text = text  # plain text
        self.html = html  # rendered inline html
        self.id = id

    def __repr__(self):
        return "HeadingInfo(%d, %r, id=%r)" % (self.level, self.text, self.id)


class Renderer:
    def __init__(self, slugger=None):
        self.slugger = slugger
        self.headings = []

    def render(self, nodes):
        return "\n".join(self.block(n) for n in nodes)

    def block(self, node):
        method = getattr(self, "render_" + type(node).__name__.lower())
        return method(node)

    # -- leaf blocks -------------------------------------------------------
    def render_heading(self, node):
        html = render_inline(node.text)
        plain = plain_text(node.text)
        ident = self.slugger.slug(plain) if self.slugger is not None else None
        self.headings.append(HeadingInfo(node.level, plain, html, ident))
        attr = "" if ident is None else ' id="%s"' % escape_attr(ident)
        return "<h%d%s>%s</h%d>" % (node.level, attr, html, node.level)

    def render_paragraph(self, node):
        return "<p>%s</p>" % render_inline(node.text)

    def render_codeblock(self, node):
        cls = ' class="language-%s"' % escape_attr(node.info) if node.info else ""
        return "<pre><code%s>%s</code></pre>" % (cls, escape_code(node.code))

    def render_rule(self, node):
        return "<hr>"

    # -- containers --------------------------------------------------------
    def render_quote(self, node):
        inner = self.render(node.blocks)
        return "<blockquote>\n%s\n</blockquote>" % inner if inner else "<blockquote>\n</blockquote>"

    def render_listblock(self, node):
        tag = "ol" if node.ordered else "ul"
        attr = ' start="%d"' % node.start if node.ordered and node.start != 1 else ""
        out = ["<%s%s>" % (tag, attr)]
        for item in node.items:
            out.append(self._item(item, node.loose))
        out.append("</%s>" % tag)
        return "\n".join(out)

    def _item(self, blocks, loose):
        if not blocks:
            return "<li></li>"
        parts = []
        for index, block in enumerate(blocks):
            if isinstance(block, B.Paragraph) and not loose:
                text = render_inline(block.text)
                parts.append(text)
            else:
                parts.append(self.block(block))
        only_inline = all(isinstance(b, B.Paragraph) for b in blocks) and not loose
        if only_inline:
            return "<li>%s</li>" % "\n".join(parts)
        return "<li>%s\n</li>" % "\n".join(parts)

    def render_table(self, node):
        def cell(tag, text, align):
            attr = ' align="%s"' % align if align else ""
            return "<%s%s>%s</%s>" % (tag, attr, render_inline(text), tag)

        out = ["<table>", "<thead>"]
        out.append("<tr>%s</tr>" % "".join(cell("th", t, a) for t, a in zip(node.header, node.aligns)))
        out.append("</thead>")
        if node.rows:
            out.append("<tbody>")
            for row in node.rows:
                out.append("<tr>%s</tr>" % "".join(cell("td", t, a) for t, a in zip(row, node.aligns)))
            out.append("</tbody>")
        out.append("</table>")
        return "\n".join(out)
