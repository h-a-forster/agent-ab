# textmerge

Line-based diff and three-way merge for a tiny version-control tool.

```python
from textmerge import diff, apply_diff, merge_text, split_lines

a = split_lines("one\ntwo\nthree\n")
b = split_lines("one\n2\nthree\n")
ops = diff(a, b)           # [("=", "one\n"), ("-", "two\n"), ("+", "2\n"), ("=", "three\n")]
apply_diff(a, ops) == b

merge_text(base, ours, theirs)   # file-level only today; raises MergeConflict
```

* `lines.py` `split_lines` / `join_lines`: a line keeps its own ending, only `"\n"` ends a line
* `diff.py`  `diff(a, b)` (full LCS table, quadratic) and `apply_diff`
* `merge.py` `merge_text` and `MergeConflict`

Run the tests with `python -m unittest discover -s tests -t .`.
