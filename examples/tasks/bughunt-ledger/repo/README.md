# ledgerlib

A small double-entry bookkeeping library: money, chart of accounts, journal, ledger,
reports and a CSV importer.

```python
from datetime import date
from ledgerlib import Chart, Ledger, Money

chart = Chart()
chart.add("1000", "Assets", "asset")
chart.add("1100", "Cash", "asset", parent="1000")
chart.add("4000", "Income", "income")
ledger = Ledger(chart)
ledger.post(date(2024, 1, 5), "Sale", [("1100", Money(5000)), ("4000", Money(-5000))])
ledger.balance("1100")            # Money(5000, 'USD')
```

Conventions (these are the documented behaviour of the library):

* `Money` is an integer number of cents. `allocate`/`split` hand leftover cents out one at a
  time to the first parts; negative amounts mirror the positive case.
* Currency conversion rounds half away from zero to a whole cent (`RateTable.convert`).
* In a journal entry positive line amounts are debits and negative ones are credits.
  `Journal.between(a, b)` is inclusive at both ends.
* `Chart.descendants(code)` lists the accounts *below* `code`, never `code` itself.
  `Ledger.balance(code, rollup=True)` adds the balances of all descendants to the account's own.
* Entries own their `tags` list; mutating one entry's tags never affects another entry
  or a list the caller passed in.
* Reporting periods follow the Gregorian calendar (`ledgerlib.periods`).
* `parse_amount` understands `1,234.50`, `$5`, `-0.05` and `(12.50)` (parentheses = negative).
* `Ledger` caches balances; the cache must never return a stale value after the journal changes.

Run the tests with `python -m unittest discover -s tests -t .`.
