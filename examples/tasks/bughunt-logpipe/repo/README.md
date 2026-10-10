# logpipe

A small log-ingestion pipeline: parsers for common log format, JSON lines and logfmt; level and
field filters; deduplication; enrichment; tumbling-window aggregation; batching sinks.

```python
from logpipe import Pipeline, MemorySink, min_level

sink = MemorySink(batch_size=100)
pipeline = Pipeline(sink, predicate=min_level("WARN"))
result = pipeline.run(lines)
sink.records()
```

Documented behaviour:

* **Timestamps** are converted to UTC epoch seconds. `2024-03-10T12:00:00+05:30` is 06:30 UTC:
  a positive offset means the local clock is ahead of UTC, so the offset is *subtracted* (this
  holds for ISO timestamps, logfmt/JSON `ts` values and common-log `[... +0200]` times alike).
* **Levels** are ordered DEBUG < INFO < WARN < ERROR < FATAL (with aliases such as `WARNING`).
  `min_level("WARN")` keeps WARN, ERROR and FATAL records.
* **Percentiles** are nearest-rank: the 50th percentile of `[1, 2, 3, 4]` is `2`, the 75th is `3`.
* **Windows** are tumbling and aligned to the epoch: `bucket_start(59.6, 60) == 0`,
  `bucket_start(90, 60) == 60`.
* **Deduper(window)** drops a record when the same key was *emitted* less than `window` seconds
  earlier. Dropped records do not extend the quiet period.
* **BatchSink**: a full batch is written immediately; `close()` writes the remaining records
  (`Pipeline.run` closes its sink at the end, so nothing is left behind).
* **Enricher** gives every record its own `fields` dict (never shared between records or with
  the defaults) and never changes its defaults.

Run the tests with `python -m unittest discover -s tests -t .`.
