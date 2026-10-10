# miniargs

A tiny declarative command-line parser (we avoid argparse's exit-on-error behaviour in our
tooling): it raises `UsageError` instead of printing and exiting.

```python
from miniargs import Option, Parser, Positional, UsageError

parser = Parser(
    options=[
        Option("verbose", short="v", kind="flag"),
        Option("output", short="o", kind="value"),
        Option("retries", kind="value", type=int, default=3),
    ],
    positionals=[Positional("source")],
)
ns = parser.parse(["-v", "--output", "out.txt", "in.txt"])
ns.verbose, ns.output, ns.retries, ns.source   # True 'out.txt' 3 'in.txt'
```

* `spec.py`   `Option` and `Positional` declarations
* `result.py` `Namespace`: attribute / item access, `to_dict()`; dashes in option names become
  underscores (`--dry-run` -> `ns.dry_run`)
* `parser.py` `Parser(options, positionals)` and `Parser.parse(argv)`; `UsageError` (a `ValueError`)

Current rules: `--name value` for value options, `--flag` for flags, `-v` / `-o value` for
short forms (one option per token), positionals in order. Unknown options, missing values,
failed type conversions and missing required arguments raise `UsageError` whose message names
the offending option or argument.

Run the tests with `python -m unittest discover -s tests -t .`.
