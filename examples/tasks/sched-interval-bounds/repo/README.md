# ivl

Tiny interval toolkit for the booking scheduler. Intervals are half-open (`[lo, hi)`), so
back-to-back bookings such as `[9, 10)` and `[10, 11)` do not collide.

```python
from ivl import Interval, merge, subtract, gaps, parse

merge([Interval(1, 3), Interval(3, 5)])      # [Interval(1, 5)]
subtract(Interval(0, 10), Interval(3, 5))    # [Interval(0, 3), Interval(5, 10)]
gaps([Interval(2, 4)], Interval(0, 10))      # [Interval(0, 2), Interval(4, 10)]
parse("[1, 5)")                              # Interval(1, 5)
```

Modules: `model.py` (the `Interval` type), `ops.py` (set operations), `text.py` (parse/format).

Run the tests with `python -m unittest discover -s tests -t .`.
