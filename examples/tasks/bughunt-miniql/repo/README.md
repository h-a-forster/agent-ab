# miniql

A tiny SQL-like query engine over lists of dicts.

```python
from miniql import Database

db = Database()
db.create_table("emp", ["id", "name", "dept", "salary"])
db.insert("emp", {"id": 1, "name": "Alice", "dept": "eng", "salary": 100})
db.insert("emp", {"id": 2, "name": "Bob", "dept": "ops", "salary": 80})
db.query("SELECT dept, SUM(salary) AS total FROM emp GROUP BY dept ORDER BY total DESC")
# [{'dept': 'eng', 'total': 100}, {'dept': 'ops', 'total': 80}]
```

Supported: `SELECT [DISTINCT] items FROM table [WHERE e] [GROUP BY e,...] [HAVING e]
[ORDER BY e [ASC|DESC],...] [LIMIT n [OFFSET m] | OFFSET m]`, arithmetic, comparisons,
`AND`/`OR`/`NOT`, `IS [NOT] NULL`, `[NOT] LIKE`, `[NOT] IN (...)`, `[NOT] BETWEEN`, `CASE`,
scalar functions (`UPPER LOWER TRIM LENGTH ABS ROUND SUBSTR COALESCE`) and aggregates
(`COUNT SUM AVG MIN MAX`, `COUNT(*)`, `COUNT(DISTINCT x)`).

Documented semantics (the behaviour the engine is meant to have):

* SQL operator precedence: `NOT` binds tighter than `AND`, which binds tighter than `OR`.
* Three-valued logic: any comparison with NULL is NULL (unknown); `NOT NULL` is NULL;
  `x IN (...)` is NULL (not false) when nothing matches but the list contains a NULL; a WHERE or
  HAVING condition keeps a row only if it is true.
* `ORDER BY` is a stable sort. NULL sorts before every other value in ascending order (so
  last in descending order). Rows that tie keep their previous relative order, in both
  directions. With several keys, earlier keys take priority.
* In `ORDER BY`, a name that is both a column and a SELECT-list alias refers to the alias
  (the output value); in `WHERE` and `GROUP BY` it refers to the column.
* `LIMIT n OFFSET m` skips `m` rows, then returns at most `n` rows.
* `LIKE` is case-sensitive: `%` matches any run of characters, `_` exactly one character;
  every other character in the pattern, including `.`, `+`, `[`, `(`, matches itself.
* Query results and tables never share row dicts: modifying a returned row does not change
  the table, and modifying a dict after inserting it does not change the table.

Run the tests with `python -m unittest discover -s tests -t .`.
