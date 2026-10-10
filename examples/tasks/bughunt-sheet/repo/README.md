# sheetcalc

A small spreadsheet engine: A1-style cells, formulas, ranges, functions, dependency
tracking with cached evaluation, formula copying and CSV import/export.

```python
from sheetcalc import Sheet

s = Sheet()
s.set_many({"A1": "10", "A2": "32", "A3": "=SUM(A1:A2)*2", "B1": '="total: "&A3'})
s.get("A3")      # 84
s.get("B1")      # 'total: 84'
s.set("A1", "0")
s.get("B1")      # 'total: 64'
```

Documented behaviour:

* Column letters: `A`=1 ... `Z`=26, `AA`=27, `AZ`=52, `ZZ`=702, `AAA`=703.
* Operator precedence, loosest first: comparisons (`= <> < <= > >=`), then `&` (text
  concatenation), then `+ -`, then `* /`, then unary `-`/`+`, then `^`. So `="a"&1+2` is `"a3"`,
  `-2^2` is `-4`, and `2^3^2` is `512` (`^` is right associative).
* A range `B2:A1` means the same cells as `A1:B2` (corners in any order), everywhere:
  functions, dependency tracking, `expand_range`.
* `ROUND(x, n)` rounds half away from zero on the decimal representation: `ROUND(2.5)` is `3`,
  `ROUND(-2.5)` is `-3`, `ROUND(2.675, 2)` is `2.68`, `ROUND(1250, -2)` is `1300`.
* `IF` and `IFERROR` only evaluate the branch that is used: `IF(A1=0, 0, 10/A1)` never
  divides by zero when `A1` is 0.
* Cached values are never stale: changing a cell updates every cell that depends on it,
  directly or through other cells, including dependencies through ranges.
* `Sheet.copy(src, dst)` / `fill_down` move relative references like a spreadsheet paste:
  `$` keeps the column and/or the row fixed (`$A1`: column fixed, `A$1`: row fixed, `$A$1`: both).
* Errors are values: `#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`, `#NUM!`, `#CYCLE!` (circular
  references) and `#ERROR!` (syntax error); they propagate through formulas.

Run the tests with `python -m unittest discover -s tests -t .`.
