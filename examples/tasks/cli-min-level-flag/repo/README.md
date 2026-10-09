# levelcount

Count log lines per severity level across one or more log files.

```console
$ python -m levelcount app.log worker.log
INFO     120
WARNING  7
ERROR    2
TOTAL    129
$ python -m levelcount --json app.log
{"INFO": 80, "WARNING": 3}
```

A line's level is its second whitespace-separated field (`2024-05-01T10:00:00 WARNING ...`),
case-insensitive, optionally in brackets. `WARN`, `ERR` and `FATAL` are accepted as aliases.
Lines without a recognised level are ignored.

Run the tests with `python -m unittest discover -s tests -t .`.
