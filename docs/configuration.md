# Configuration

An experiment is one TOML file, usually `experiment.toml`. Each task has its own
`task.toml`; see [tasks.md](tasks.md).

Rules:

- Unknown keys are errors. The message names the key path, for example
  `experiment.toml: arms[1].agent.modle`.
- Relative paths resolve against the experiment file's directory.
- Workspace paths (`remove`, overlay contents) must stay inside the workspace. Absolute
  paths and `..` are rejected.
- Names (`name`, arm names, task ids) must match `^[A-Za-z0-9][A-Za-z0-9._-]*$`.
- Numeric settings (timeouts, `budget_usd`) must be greater than 0.
- Configuration errors exit with code 2.

## Top-level keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | Experiment name. Used in the default run directory name. |
| `description` | string | `""` | Free text. Stored in `run.json`; not shown in reports. |
| `tasks` | list of strings | required | Glob patterns. Each match must be a directory with a `task.toml`. |
| `exclude_tasks` | list of strings | `[]` | Task ids or globs to leave out. |
| `repeats` | integer >= 1 | `1` | Trials per task per arm. |
| `jobs` | integer >= 1 | `1` | Concurrent trials. |
| `seed` | integer | `0` | Seeds the trial order and each trial's seed. |
| `budget_usd` | number > 0 | none | Stop starting new trials once recorded spend reaches this. |
| `timeout_s` | number > 0 | `1800` | Agent time limit per attempt. Also limits `setup`. A task can override it. |
| `check_timeout_s` | number > 0 | `600` | Check time limit. A task can override it. A timed-out check is a fail. |
| `max_retries` | integer >= 0 | `2` | Extra attempts after an infrastructure error. |
| `timeout_is_failure` | boolean | `true` | An agent timeout is a fail, without running the check. If `false`, the check runs on what the agent left. |
| `baseline` | string | first arm | Arm the others are compared with. |
| `keep_workspaces` | boolean | `false` | Keep workspaces. The path is written to `workspace.txt` in the attempt directory. |
| `workspace_root` | string | system temp | Directory for workspaces. |

Duplicate task ids and an empty task list are errors.

### Budget

`budget_usd` is checked before each trial starts, against all spend recorded in the run
directory, including earlier sessions of a resumed run. Running trials are not stopped, so
spend can exceed the budget by up to `jobs` trials. Trials that report no cost count as zero:
a trial that times out may report none, and with an adapter that never reports cost the
budget has no effect.

## `[agent]`

Defaults for every arm.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `adapter` | string | required (here or in each arm) | `claude-code`, `codex`, `command` or `mock`. |
| `model` | string | none | Passed to the agent's model flag. |
| `effort` | string | none | Passed to the agent's effort setting. Checked by the adapter. |
| `args` | list of strings | `[]` | Extra CLI arguments, appended after the adapter's own. |
| `env` | table of strings | `{}` | Variables added to the inherited environment. Values are redacted in `run.json`; names are kept. |
| `command` | list of strings | none | Argv template for the `command` adapter. |
| `options` | table | `{}` | Adapter options (`[agent.options]`). Unknown keys are errors. See [adapters.md](adapters.md). |

## `[[arms]]`

`run` needs at least two arms; `validate` accepts one. Names must be unique.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `name` | string | required | Arm name. |
| `description` | string | `""` | Free text. Stored in `run.json`; not shown in reports. |
| `prompt_prefix` | string | `""` | Text before the task prompt. |
| `prompt_suffix` | string | `""` | Text after the task prompt. |
| `overlay` | string | none | Directory copied onto the workspace before the agent runs. |
| `remove` | list of strings | `[]` | Workspace paths deleted before the overlay is applied. |
| `agent` | table | `{}` | Overrides of `[agent]` (`[arms.agent]`, `[arms.agent.options]`). |

The prompt is prefix, task prompt and suffix, joined by blank lines.

The git snapshot is taken after `remove` and `overlay`, so the recorded diff holds only the
agent's changes.

### Merge rules

| Field | Rule |
|---|---|
| `adapter`, `model`, `effort`, `command` | Arm value replaces the default. |
| `args` | Concatenated: default first, then the arm's. |
| `env`, `options` | Shallow merge; the arm wins. |

```toml
[agent]
adapter = "claude-code"
model = "sonnet"
args = ["--verbose"]
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
[arms.agent.options]
max_turns = 80
```

`opus-strict` resolves to model `opus`, args `["--verbose"]` and options
`{permission_mode = "bypassPermissions", max_turns = 80}`.

## Placeholders

Task `check` and `setup` commands accept `{python}` (the interpreter running agent-ab) and
`{workspace}` (the trial's workspace).

The `command` adapter's template also accepts `{prompt_file}`, `{prompt}`, `{artifacts}`,
`{model}`, `{effort}`, `{seed}` and `{root}`. See [adapters.md](adapters.md#command).

Write literal braces as `{{` and `}}`. Unknown placeholders are errors when the config loads.

## Command-line overrides

| Option | Overrides |
|---|---|
| `--jobs N` | `jobs` |
| `--repeats N` | `repeats` |
| `--budget USD` | `budget_usd` (must be > 0) |
| `--keep-workspaces` | `keep_workspaces` |
| `--arms A,B` | Selects arms. The baseline must be included. |
| `--only GLOB` | Selects tasks by id. Repeatable. |

## Fingerprint

Each run stores a SHA-256 fingerprint of the resolved configuration plus the content of
every file in every task and overlay directory (ignoring `.git`, `__pycache__` and `*.pyc`).
`--resume` refuses a run whose fingerprint differs, unless you pass `--force`.

Excluded from the fingerprint, so they may change between sessions: `jobs`,
`keep_workspaces`, `workspace_root`, `budget_usd` and descriptions.

Everything else is included: `repeats`, `max_retries`, agent settings, `env` values, and any
edit to a task, check or overlay file. `--arms` and `--only` change the resolved
configuration, so resume with the same selection. See
[run-directory.md](run-directory.md#resume).
