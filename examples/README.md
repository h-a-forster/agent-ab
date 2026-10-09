# Examples

| Path | Contents |
|---|---|
| [`quickstart/`](quickstart/experiment.toml) | Offline demo with the `mock` adapter: three arms, no API key, no cost. |
| [`claude-code/`](claude-code/experiment.toml) | Template: does telling Claude Code not to write tests change pass rate and cost? |
| [`codex/`](codex/experiment.toml) | Template: Codex reasoning effort `low` vs `high`. |
| [`tasks/`](tasks/) | Ten small Python tasks used by all three. |

```sh
agent-ab validate examples/quickstart/experiment.toml --tasks
agent-ab run examples/quickstart/experiment.toml
```

The templates run real agents with broad permissions and cost money. Read the comments at
the top of each file first, and use a container or VM. See [docs/safety.md](../docs/safety.md).

## Tasks

All tasks are standard-library Python 3.11+, deterministic and network-free.

| Task | Kind | Difficulty |
|---|---|---|
| `pagination-off-by-one` | bugfix | easy |
| `cli-min-level-flag` | feature | easy |
| `money-decimal-rounding` | bugfix | easy |
| `csv-quoted-newlines` | bugfix | medium |
| `config-validation-errors` | feature | medium |
| `semver-precedence` | feature | medium |
| `dedupe-quadratic` | perf | medium |
| `portable-path-normalize` | bugfix | medium |
| `dst-daily-schedule` | bugfix | hard |
| `lru-cache-thread-safety` | bugfix | hard |

Each task follows the layout in [docs/tasks.md](../docs/tasks.md):

```text
tasks/<task-id>/
  task.toml
  repo/                  starting files, including visible tests
  checks/checks/         hidden tests; land at <workspace>/checks/ after the agent finishes
  solution/              reference fix
```

The check is `{python} -m unittest discover -s checks -t .`, run from the workspace root.
