# Configuration reference

An experiment is described by one TOML file, conventionally `experiment.toml`. Each task is a
directory with its own `task.toml` (see [tasks.md](tasks.md)). This page documents every key.

General rules:

- **Unknown keys are errors**, anywhere in the file. The error names the key path, for
  example `experiment.toml: arms[1].agent.modle`.
- Relative paths resolve against the directory containing the experiment file.
- Paths used inside the workspace (`overlay` contents, `remove`) must stay inside it:
  absolute paths and `..` are rejected.
- Names (`name`, arm names, task ids) must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`.
- Configuration errors exit with code 2 and print `agent-ab: error: <message>`.

## Top-level keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | Experiment name. Used in the default run directory name and checked on resume. |
| `description` | string | `""` | Free text shown in reports. |
| `tasks` | list of strings | required | Glob patterns, relative to the experiment file. A match counts if it is a directory containing `task.toml`. |
| `exclude_tasks` | list of strings | `[]` | Task ids or glob patterns (matched against the task id) to leave out. |
| `repeats` | integer >= 1 | `1` | Trials per task per arm. |
| `jobs` | integer >= 1 | `1` | Trials run concurrently. |
| `seed` | integer | `0` | Seeds the trial order and each trial's seed. |
| `budget_usd` | float | none | Stop launching new trials once recorded spend reaches this value. |
| `timeout_s` | float | `1800` | Agent wall-clock limit per attempt, in seconds. A task's `timeout_s` overrides it. |
| `check_timeout_s` | float | `600` | Limit for the hidden check. A task's `check_timeout_s` overrides it. A check that times out is a fail. |
| `max_retries` | integer >= 0 | `2` | Extra attempts after an infrastructure error. Attempts are numbered from 0, so a trial gets at most `max_retries + 1` attempts. |
| `timeout_is_failure` | boolean | `true` | If the agent times out, record a fail without running the check. If `false`, the check runs on whatever the agent left behind. |
| `baseline` | string | first arm | Arm every other arm is compared against. |
| `keep_workspaces` | boolean | `false` | Keep each trial's workspace instead of deleting it. Its path is written to `workspace.txt` in the attempt directory. |
| `workspace_root` | string | system temp | Directory under which workspaces are created. |

Duplicate task ids (the same directory name matched by different globs) and an empty task
list are errors.

### Budget

`budget_usd` is checked before each trial starts, against the total cost recorded in the
run directory, including earlier sessions of a resumed run. Trials already running are not
stopped, so spend can exceed the budget by up to `jobs` trials. Trials that report no cost
count as zero, so a budget has no effect with an adapter that does not report cost.

### Example

```toml
name = "effort-high-vs-medium"
description = "Does high effort pay for itself?"
tasks = ["tasks/*", "more-tasks/*"]
exclude_tasks = ["slow-*"]
repeats = 3
jobs = 4
seed = 7
budget_usd = 40.0
timeout_s = 1200
check_timeout_s = 300
max_retries = 2
timeout_is_failure = true
baseline = "medium"
```

## `[agent]`: defaults for every arm

| Key | Type | Default | Meaning |
|---|---|---|---|
| `adapter` | string | required (here or in every arm) | `claude-code`, `codex`, `command` or `mock`. |
| `model` | string | none | Passed to the agent's model flag. Omit to use the agent's default. |
| `effort` | string | none | Passed to the agent's effort setting. Validated by the adapter. |
| `args` | list of strings | `[]` | Extra CLI arguments appended after the adapter's own arguments. |
| `env` | table of strings | `{}` | Environment variables added to the inherited environment. |
| `command` | list of strings | none | Argv template for the `command` adapter. |
| `options` | table | `{}` | Adapter-specific options, written as `[agent.options]`. Validated by the adapter; unknown keys are errors. See [adapters.md](adapters.md). |

```toml
[agent]
adapter = "claude-code"
model = "sonnet"
effort = "medium"
args = []
env = { CI = "1" }

[agent.options]
permission_mode = "bypassPermissions"
max_turns = 60
```

## `[[arms]]`

At least two arms are required for `run`; `validate` accepts one. Arm names must be unique.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | Arm name. |
| `description` | string | `""` | Free text shown in reports. |
| `prompt_prefix` | string | `""` | Text placed before the task prompt. |
| `prompt_suffix` | string | `""` | Text placed after the task prompt. |
| `overlay` | string | none | Directory, relative to the experiment file, copied onto the workspace before the agent runs. |
| `remove` | list of strings | `[]` | Workspace-relative paths deleted before the overlay is applied. |
| `agent` | table | `{}` | Per-arm overrides of `[agent]`, written as `[arms.agent]` and `[arms.agent.options]`. |

The prompt sent to the agent is the prefix, the task prompt and the suffix, joined by blank
lines, with surrounding whitespace stripped.

The workspace is snapshotted with git **after** `remove` and `overlay` are applied, so the
recorded diff contains only the agent's changes, not the arm's files.

### Merge rules for `[arms.agent]`

| Field | Rule |
|---|---|
| `adapter`, `model`, `effort` | Arm value replaces the default. |
| `command` | Arm value replaces the default. |
| `args` | Concatenated: `[agent].args` first, then the arm's `args`. |
| `env` | Shallow merge; the arm wins on conflicting keys. |
| `options` | Shallow merge; the arm wins on conflicting keys. |

Example:

```toml
[agent]
adapter = "claude-code"
model = "sonnet"
args = ["--verbose"]
env = { A = "1" }
[agent.options]
permission_mode = "bypassPermissions"
max_turns = 40

[[arms]]
name = "control"

[[arms]]
name = "opus-strict"
prompt_suffix = "Run the full test suite before you finish."
overlay = "arms/strict"
remove = ["AGENTS.md"]
[arms.agent]
model = "opus"
args = ["--foo"]
env = { B = "2" }
[arms.agent.options]
max_turns = 80
```

The resolved `opus-strict` arm uses model `opus`, args `["--verbose", "--foo"]`, env
`{A = "1", B = "2"}`, and options `{permission_mode = "bypassPermissions", max_turns = 80}`.

## Placeholders

Task `check` and `setup` commands (argv items or a shell string) accept:

| Placeholder | Expands to |
|---|---|
| `{python}` | The Python interpreter running agent-ab. |
| `{workspace}` | The trial's workspace path. |

The `command` adapter's argv template accepts `{prompt_file}`, `{prompt}`, `{workspace}`,
`{artifacts}`, `{model}`, `{effort}`, `{python}` and `{seed}`. See
[adapters.md](adapters.md#command).

Write a literal brace as `{{` or `}}`. An unknown placeholder is a configuration error,
reported when the configuration is loaded.

## Command-line overrides

Some keys can be overridden for a single `run`:

| Option | Overrides |
|---|---|
| `--jobs N` | `jobs` |
| `--repeats N` | `repeats` |
| `--budget USD` | `budget_usd` |
| `--keep-workspaces` | `keep_workspaces` |
| `--arms a,b` | selects arms; the baseline must be among them |
| `--only GLOB` | selects tasks by id |

## Fingerprint

Each run records a fingerprint: a SHA-256 hash of the resolved configuration plus the path
and content hash of every file in every task directory and overlay directory (ignoring
`__pycache__`, `.git` and `*.pyc`). `--resume` refuses to continue a run whose fingerprint
differs from the current configuration unless you pass `--force`.

These keys are excluded from the fingerprint and may change between sessions of the same
run: `jobs`, `keep_workspaces`, `workspace_root`, `budget_usd`, `description`.

Everything else is included. In particular, changing `repeats` (or passing a different
`--repeats`), editing a task, a check, or an overlay file changes the fingerprint. Selecting
arms or tasks with `--arms` or `--only` changes the set of arms and tasks in the resolved
configuration, so resume with the same selection you started with.

See [run-directory.md](run-directory.md#resume) for resume semantics.
