"""Table of contents built from rendered headings."""

from .escape import escape_attr


class _Entry:
    def __init__(self, heading):
        self.heading = heading
        self.children = []


def build_tree(headings, min_depth=1, max_depth=3):
    """Nest headings with ``min_depth <= level <= max_depth`` by their levels."""
    roots = []
    stack = []
    for heading in headings:
        if heading.level < min_depth or heading.level > max_depth:
            continue
        entry = _Entry(heading)
        while stack and stack[-1].heading.level >= heading.level:
            stack.pop()
        (stack[-1].children if stack else roots).append(entry)
        stack.append(entry)
    return roots


def render_toc(headings, min_depth=1, max_depth=3):
    """An HTML nested ``<ul>`` of links to the headings' ids ('' when there are none)."""
    roots = build_tree(headings, min_depth, max_depth)
    return _render(roots) if roots else ""


def _render(entries):
    lines = ["<ul>"]
    for entry in entries:
        link = '<a href="#%s">%s</a>' % (escape_attr(entry.heading.id), entry.heading.html)
        if entry.children:
            lines.extend(["<li>" + link, _render(entry.children), "</li>"])
        else:
            lines.append("<li>%s</li>" % link)
    lines.append("</ul>")
    return "\n".join(lines)


def outline(headings, min_depth=1, max_depth=3):
    """Plain-text outline, two spaces of indent per nesting level."""
    out = []

    def walk(entries, depth):
        for entry in entries:
            out.append("%s%s" % ("  " * depth, entry.heading.text))
            walk(entry.children, depth + 1)

    walk(build_tree(headings, min_depth, max_depth), 0)
    return "\n".join(out)
