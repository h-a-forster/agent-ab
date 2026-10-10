# sessions

Turns raw JSON-lines event logs into per-user sessions and daily statistics for the analytics
dashboard.

```python
from datetime import timedelta
from sessions import daily_report, load_events, sessionize

events = load_events(open("events.jsonl"))
daily_report(sessionize(events, gap=timedelta(minutes=30)))
```

Run the tests with `python -m unittest discover -s tests -t .`.
