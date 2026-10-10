# inix

A small INI reader/writer used by the deploy tooling.

```python
from inix import Config

cfg = Config.from_string("[db]\nhost = localhost\nport = 5432\n")
cfg.get("db", "host")      # 'localhost'
cfg.getint("db", "port")   # 5432
```

Run the tests with `python -m unittest discover -s tests -t .`.
