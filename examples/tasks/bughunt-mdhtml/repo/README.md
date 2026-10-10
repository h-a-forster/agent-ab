# mdhtml

A small markdown-to-HTML renderer (headings, paragraphs, emphasis, code, links, images,
lists, block quotes, tables, fenced code, table of contents).

```python
from mdhtml import render, render_document

render("# Hello *world*")                 # '<h1 id="hello-world">Hello <em>world</em></h1>'
doc = render_document("# A\n## B\n")
doc.toc()                                  # nested <ul> of links to heading ids
```

Documented behaviour:

* Heading ids are unique **within one document**: `Intro`, `Intro`, `Intro` get `intro`,
  `intro-1`, `intro-2`. Every call to `render` / `render_document` (and every new
  `Slugger()`) starts with a clean slate. The table of contents links to the very same ids.
* Code spans are literal: nothing inside backticks is treated as markup, and a backslash
  escape such as `\*` produces a literal character instead of emphasis.
* Everything that goes into an HTML attribute (link `href`, image `src` and `alt`, autolinks)
  is attribute-escaped, so a `"` in it becomes `&quot;` and `&` becomes `&amp;`.
* A list is *loose* (items wrapped in `<p>`) when a blank line separates any two of its
  items; otherwise it is tight. Nested lists decide for themselves.
* In pipe tables `\|` is a literal pipe inside a cell, in header and body rows.
* A fenced code block is closed by a fence made of the same character that is at least as
  long as the opening fence; shorter fences inside are ordinary content.
* `<ol start="N">` is emitted whenever an ordered list does not start at 1.

Run the tests with `python -m unittest discover -s tests -t .`.
