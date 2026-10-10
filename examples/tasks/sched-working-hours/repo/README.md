# bizhours

Business-time arithmetic for SLA deadlines: "this ticket is due 600 working minutes after it
was opened". All datetimes are naive local times.

```python
from datetime import datetime
from bizhours import WorkCalendar, add_working_minutes, working_minutes_between

cal = WorkCalendar()                                   # Mon-Fri 09:00-17:00
add_working_minutes(cal, datetime(2024, 1, 5, 16, 0), 120)   # 2024-01-08 10:00
working_minutes_between(cal, datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 10))  # 60.0
```

* `calendar.py` `WorkCalendar`: when is it working time (`is_working`, `next_open`)
* `add.py`      `add_working_minutes(cal, start, minutes)`
* `elapsed.py`  `working_minutes_between(cal, a, b)`

Run the tests with `python -m unittest discover -s tests -t .`.
