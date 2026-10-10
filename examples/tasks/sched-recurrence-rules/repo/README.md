# recur

Recurrence rules for the calendar service, in the spirit of iCalendar RRULE but much smaller.

```python
from datetime import date
from recur import between, occurrences, parse_rule

rule = parse_rule("FREQ=DAILY;INTERVAL=3;COUNT=4")
list(occurrences(rule, date(2024, 1, 1)))
# [2024-01-01, 2024-01-04, 2024-01-07, 2024-01-10]
between(rule, date(2024, 1, 1), date(2024, 1, 5), date(2024, 1, 9))   # [2024-01-07]
```

* `rule.py`   the `Rule` value object and its validation
* `parse.py`  `parse_rule(text)` and `format_rule(rule)`
* `expand.py` `occurrences(rule, start)` (lazy generator) and `between(rule, start, lo, hi)`

Run the tests with `python -m unittest discover -s tests -t .`.
