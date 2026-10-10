from .chars import escape_html
from .emphasis import build_tree
from .scan import scan


def parse_inline(text):
    return build_tree(scan(text))


def render_inline(text):
    """Inline Markdown -> HTML."""
    out = []
    stack = [iter(parse_inline(text))]
    closers = []
    while stack:
        item = next(stack[-1], None)
        if item is None:
            stack.pop()
            if closers:
                out.append(closers.pop())
            continue
        kind, value = item
        if kind == "code":
            out.append("<code>%s</code>" % escape_html(value))
        elif kind == "text":
            out.append(escape_html(value))
        else:
            out.append("<%s>" % kind)
            closers.append("</%s>" % kind)
            stack.append(iter(value))
    return "".join(out)


def plain_text(text):
    """The text content of inline Markdown: escapes resolved, code span content kept,
    emphasis markers removed."""
    out = []
    stack = [iter(parse_inline(text))]
    while stack:
        item = next(stack[-1], None)
        if item is None:
            stack.pop()
            continue
        kind, value = item
        if kind in ("em", "strong"):
            stack.append(iter(value))
        else:
            out.append(value)
    return "".join(out)
