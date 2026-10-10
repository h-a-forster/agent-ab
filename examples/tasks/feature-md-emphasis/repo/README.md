# mdinline

A small Markdown renderer for README files (a subset of CommonMark).

```python
from mdinline import render_document, render_inline, outline

render_inline("use `code` and \\*escapes\\*")
render_document(open("README.md").read())
outline(md)        # [(level, plain-text title), ...] for a table of contents
```

* `chars.py`  ASCII punctuation, HTML escaping (`& < > "`)
* `scan.py`   inline scanner: backslash escapes, code spans, text
* `render.py` `render_inline`, `plain_text`
* `blocks.py` paragraphs and `#` headings, `render_document`, `outline`

Emphasis (`*` and `_`) is not implemented yet: those characters are plain text. There are no links,
images, raw HTML, hard line breaks or entity references: `&`, `<`, `>`, `"` are always literal
characters and get escaped. Newlines inside a paragraph are kept as they are.

Run the tests with `python -m unittest discover -s tests -t .`.
