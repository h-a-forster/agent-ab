# cronx

Cron expression parsing and next-run computation for the job runner.

```python
from datetime import datetime
from cronx import CronExpr, next_after

next_after(CronExpr.parse("30 2 * * 1-5"), datetime(2024, 3, 1, 12, 0))   # 2024-03-04 02:30
```

Run the tests with `python -m unittest discover -s tests -t .`.
