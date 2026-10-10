# Examples

| Path | Contents |
|---|---|
| [`quickstart/`](quickstart/experiment.toml) | Offline demo with the `mock` adapter: three arms, no API key, no cost. |
| [`claude-code/`](claude-code/experiment.toml) | Template: does telling Claude Code not to write tests change pass rate and cost? |
| [`codex/`](codex/experiment.toml) | Template: Codex reasoning effort `low` vs `high`. |
| [`tasks/`](tasks/) | Fifty Python tasks in four groups (see [Tasks](#tasks)). |

```sh
agent-ab validate examples/quickstart/experiment.toml --tasks
agent-ab run examples/quickstart/experiment.toml
```

The templates run real agents with broad permissions and cost money. Read the comments at
the top of each file first, and use a container or VM. See [docs/safety.md](../docs/safety.md).

## Tasks

All tasks are standard-library Python 3.11+, deterministic and network-free.

Each example experiment selects its tasks differently:

- `quickstart` lists the ten original tasks explicitly.
- `claude-code` uses `tasks = ["../tasks/*"]`, so it runs all 50.
- `codex` uses the same glob and also runs all 50. Trim the list before a first real run
  if you want a cheaper experiment.

[`docs/results/`](../docs/results/) holds pilots that measure these tasks on Claude Haiku 5.5
(`pilot-haiku-5-5` and `pilot2-haiku-5-5`).

Kind and difficulty come from each `task.toml`'s `tags`.

### Original tasks (10)

| Task | Kind | Difficulty | Summary |
|---|---|---|---|
| `cli-min-level-flag` | feature | easy | Add a minimum-level flag to a small CLI. |
| `config-validation-errors` | feature | medium | Report every configuration error with clear messages. |
| `csv-quoted-newlines` | bugfix | medium | Parse quoted CSV fields that contain newlines. |
| `dedupe-quadratic` | perf | medium | Remove quadratic behaviour from de-duplication. |
| `dst-daily-schedule` | bugfix | hard | Compute daily schedules correctly across daylight saving changes. |
| `lru-cache-thread-safety` | bugfix | hard | Make an LRU cache safe under threads. |
| `money-decimal-rounding` | bugfix | easy | Fix rounding in money arithmetic. |
| `pagination-off-by-one` | bugfix | easy | Fix short pages and the unreachable last page. |
| `portable-path-normalize` | bugfix | medium | Normalise paths consistently across platforms. |
| `semver-precedence` | feature | medium | Order semantic versions by the precedence rules. |

### Round 1 (20)

| Task | Kind | Difficulty | Summary |
|---|---|---|---|
| `api-config-layers` | feature | hard | Layered configuration with environment and `--set` overrides, and value provenance. |
| `api-miniargs-clusters` | feature | hard | Add short-option clusters and other conveniences to an argument parser. |
| `data-interval-sets` | performance, bugfix | hard | Fix and speed up interval-set operations. |
| `data-json-patch` | feature, bugfix | hard | Complete JSON Pointer and a JSON Patch subset (RFC 6901, 6902). |
| `data-sessionize` | bugfix, feature | hard | Fix and extend event sessionisation and reporting. |
| `graph-build-plan` | feature | hard | Deterministic, partial and parallel build plans with readable cycle reports. |
| `graph-transit-router` | feature | hard | Earliest-arrival routing with transfer times and deterministic itineraries. |
| `parse-cron-schedule` | feature | hard | Make a cron parser and `next_after` behave like Vixie cron. |
| `parse-expr-operators` | feature | hard | Extend an expression parser and evaluator with more operators. |
| `parse-ini-interpolation` | feature | hard | Add `${name}` interpolation to an INI reader. |
| `parse-query-nested` | feature, bugfix | hard | Parse and encode nested query strings. |
| `sched-interval-bounds` | feature | hard | Support open and closed interval ends. |
| `sched-recurrence-rules` | feature | hard | Extend recurrence rules beyond daily and weekly. |
| `sched-working-hours` | feature | hard | Compute SLA deadlines over real working calendars. |
| `state-hierarchical-machine` | feature | hard | Add nested states to a state machine. |
| `state-ttl-cache-tags` | feature | hard | Extend a TTL cache with tags and statistics. |
| `state-undo-history` | feature | hard | Add grouping and limits to an undo history. |
| `text-template-engine` | feature | hard | Extend a template engine with expressions and filters. |
| `text-unified-patch` | feature | hard | Apply unified diffs with offsets and malformed-input handling. |
| `text-wrap-display-width` | bugfix | hard | Wrap text by display width (ANSI codes, wide characters, accents). |

### Bug hunts (10)

Each task seeds several bugs in a codebase of roughly 800-1100 lines. The prompt lists
symptoms; the hidden checks cover every bug and a regression suite. All are `bugfix`,
`multi-file` and `bughunt`, with no difficulty tag.

| Task | Codebase |
|---|---|
| `bughunt-depres` | Semantic-version ranges and a backtracking dependency resolver. |
| `bughunt-inventory` | Warehouse catalogue, stock, reservations, pricing and shipping. |
| `bughunt-ledger` | Bookkeeping library. |
| `bughunt-logpipe` | Log-ingestion pipeline. |
| `bughunt-mdhtml` | Markdown-to-HTML renderer. |
| `bughunt-miniql` | SQL-like query engine over lists of dicts. |
| `bughunt-ratelimit` | Rate limiters and a deterministic job scheduler. |
| `bughunt-sheet` | Spreadsheet formula engine. |
| `bughunt-sitegen` | Static site generator. |
| `bughunt-textadv` | Text-adventure engine. |

### Large features (10)

All are `feature`, `hard`, `multi-file` and `differential`: hidden checks compare thousands of
seeded inputs with an oracle.

| Task | Other tags | Summary |
|---|---|---|
| `feature-decimal-context` | numeric | Rounded decimal arithmetic without the stdlib `decimal`. |
| `feature-diff3-merge` | performance | Line-level three-way merge. |
| `feature-md-emphasis` | algorithm, performance | CommonMark emphasis and strong emphasis. |
| `feature-minire` | performance | Extend a backtracking regex library. |
| `feature-paragraph-layout` | algorithm, performance | Optimal line breaking. |
| `feature-rga-text-crdt` | algorithm, performance | Replicated text sequence that converges. |
| `feature-rope-buffer` | performance | Rope-backed editor buffer with markers and undo groups. |
| `feature-sql-select` | parser | Small SQL SELECT engine checked against SQLite. |
| `feature-toml-config` | parser | TOML parser written without a TOML library. |
| `feature-uri-resolve` | rfc | RFC 3986 parsing and reference resolution. |

Each task follows the layout in [docs/tasks.md](../docs/tasks.md):

```text
tasks/<task-id>/
  task.toml
  repo/                  starting files, including visible tests
  checks/checks/         hidden tests; land at <workspace>/checks/ after the agent finishes
  solution/              reference fix
```

The check is `{python} -m unittest discover -s checks -t .`, run from the workspace root.
