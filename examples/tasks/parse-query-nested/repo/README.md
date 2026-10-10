# qs

Query-string parsing and encoding for our HTTP gateway.

```python
from qs import encode, parse

parse("a=1&b=x%20y&a=2")   # {'a': ['1', '2'], 'b': 'x y'}
encode({"q": "a b"})        # 'q=a%20b'
```

Run the tests with `python -m unittest discover -s tests -t .`.
