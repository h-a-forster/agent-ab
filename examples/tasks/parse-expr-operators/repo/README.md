# calc

A small expression language used by the report templates.

```python
from calc import eval_expr, parse, to_source

eval_expr("1 + 2 * x", {"x": 3})     # 7
to_source(parse("(1 + 2) * 3"))       # '(1 + 2) * 3'
```

Run the tests with `python -m unittest discover -s tests -t .`.
