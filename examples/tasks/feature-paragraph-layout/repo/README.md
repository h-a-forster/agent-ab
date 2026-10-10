# layout

Text layout helpers for a terminal documentation tool.

```python
from layout import format_paragraph, format_text

format_paragraph("the quick brown fox jumps", 12)               # ['the quick', 'brown fox', 'jumps']
format_paragraph("the quick brown fox jumps", 12, align="justify")
format_text(open("README.txt").read(), 72, align="left", indent=4)
```

* `wrap.py`      `wrap(words, width)`: greedy line filling
* `align.py`     `align_line`, `justify_words` (extra spaces are shared evenly, the leftover ones go to
                 the leftmost gaps; the last line of a paragraph is never justified)
* `paragraph.py` `format_paragraph(text, width, align="left", indent=0)` -> list of lines,
                 `format_text(text, width, **kwargs)` -> paragraphs (split on blank lines) joined by one
                 empty line

Widths are in characters (`len`). Run the tests with `python -m unittest discover -s tests -t .`.
