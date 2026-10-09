# archpath

Path handling for an archive tool. Member paths come from archives produced on Windows,
macOS and Linux and are normalised to a canonical relative form before extraction, so that
`docs/./a.txt` and `docs/a.txt` are the same member and `../../etc/passwd` is rejected.

```python
from archpath import normalize, split_parts

normalize("docs/./guide/../a.txt")   # 'docs/a.txt'
split_parts("docs/a.txt")            # ['docs', 'a.txt']
```

Run the tests with `python -m unittest discover -s tests -t .`.
