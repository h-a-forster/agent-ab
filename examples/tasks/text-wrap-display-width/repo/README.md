# wrapkit

Small helpers for laying out terminal text.

```python
from wrapkit import render_table, wrap

wrap("the quick brown fox", 10)               # ['the quick', 'brown fox']
render_table([["a", "b c d"]], [3, 3])         # 'a   | b c\n    | d'
```

Run the tests with `python -m unittest discover -s tests -t .`.
