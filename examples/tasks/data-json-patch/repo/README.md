# jpatch

JSON Pointer (RFC 6901) and JSON Patch (RFC 6902) helpers for the config sync service.

```python
from jpatch import apply_patch, diff

new = apply_patch({"a": 1}, [{"op": "add", "path": "/b", "value": 2}])   # {'a': 1, 'b': 2}
diff({"a": 1}, {"a": 2})                                                 # [{'op': 'replace', 'path': '/a', 'value': 2}]
```

Run the tests with `python -m unittest discover -s tests -t .`.
