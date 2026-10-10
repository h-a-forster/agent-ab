from .chars import escape_html
from .scan import scan


def render_inline(text):
    """Inline Markdown -> HTML."""
    out = []
    for kind, value in scan(text):
        if kind == "code":
            out.append("<code>%s</code>" % escape_html(value))
        else:
            out.append(escape_html(value))
    return "".join(out)


def plain_text(text):
    """The text content of inline Markdown: escapes resolved, code span content kept."""
    return "".join(value for kind, value in scan(text))
