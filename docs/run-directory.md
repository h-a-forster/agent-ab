# Run directory

Each `agent-ab run` writes one run directory. The default is
`runs/<name>-<UTC YYYYmmdd-HHMMSS>` next to the experiment file; `--out DIR` sets another.
`--out` refuses a directory that already contains a run or leftover `trials.jsonl` or
`trials/`. `report`, `status` and `show` need only the run directory.

## Layout

```text
<run_dir>/
  run.json                 metadata and the resolved configuration
  trials.jsonl             one record per attempt, append-only
  trials/<trial_id>/attempt-<n>/
    prompt.md              prompt sent to the agent
    agent.stdout, agent.stderr
    setup.stdout, setup.stderr      if the task has setup
    check.stdout, check.stderr
    diff.patch             the agent's changes (git diff against the starting snapshot)
    usage.json             usage written by the agent (command and mock adapters)
    record.json            this attempt's record
    workspace.txt          kept workspace path (keep_workspaces only)
  report.html, report.md, analysis.json     written at the end of run
```

Files that do not apply are absent. Some adapters and failure paths add more, for example
`append_system_prompt.md` (claude-code) or `traceback.txt`.

The trial id is `<task>__<arm>__r<repeat>`, for example `fix-slugify__tdd__r2`. Repeats and
attempts count from 0.

## `run.json`

| Field | Meaning |
|---|---|
| `schema` | Schema version (`1`). |
| `tool`, `version` | `"agent-ab"` and the version that created the run. |
| `experiment` | Experiment name. |
| `fingerprint` | See [configuration.md](configuration.md#fingerprint). |
| `created_at` | ISO-8601 UTC. |
| `config` | Resolved configuration. `env` values are replaced by `"<redacted>"`; names are kept. |
| `planned_trials` | Number of planned trials. |
| `seed`, `baseline` | Experiment seed and baseline arm. |

## `trials.jsonl`

One JSON line per **attempt**, appended and flushed as each attempt finishes. A trial has
several lines when infrastructure errors forced retries; the highest `attempt` is its
result.

A crash mid-write can leave a truncated last line. Reading skips it. Before appending, a
resumed run moves it to `trials.jsonl.damaged-<timestamp>` and cuts it from the log. Damage
anywhere else is an error.

| Field | Type | Meaning |
|---|---|---|
| `trial_id`, `task`, `arm` | string | Identity. |
| `repeat`, `attempt` | integer | From 0. |
| `status` | `pass`, `fail`, `error` | `error` is an infrastructure error. |
| `passed` | boolean or null | Check outcome. |
| `agent_exit_code` | integer or null | Null if the agent did not start or was killed. |
| `agent_timed_out` | boolean | Agent hit its time limit. |
| `check_exit_code` | integer or null | Null if the check did not run. |
| `check_timed_out` | boolean | Check hit its time limit (a fail). |
| `duration_s`, `check_duration_s` | number or null | Wall-clock seconds. |
| `cost_usd` | number or null | Reported cost. |
| `input_tokens`, `output_tokens` | integer or null | Tokens. |
| `cache_read_tokens`, `cache_write_tokens` | integer or null | Cache tokens. |
| `turns` | integer or null | Agent turns. |
| `files_changed`, `lines_added`, `lines_removed` | integer or null | From the agent's diff. |
| `error` | string or null | Error or diagnostic text. |
| `started_at`, `finished_at` | string or null | ISO-8601 UTC. |
| `artifacts` | string or null | Attempt directory, relative, with forward slashes. |
| `schema` | integer | Record schema version (`1`). |

`null` means unknown, never zero. Statistics skip unknown values.

```python
import json
from pathlib import Path

rows = [json.loads(l) for l in Path("trials.jsonl").read_text("utf-8").splitlines() if l]
```

Keep only the last attempt per `trial_id` before computing anything.

## Resume

```sh
agent-ab run experiment.toml --resume runs/my-experiment-20260101-120000
```

A trial is done when its last attempt is `pass` or `fail`, or is `error` with retries used
up. Resuming:

1. Checks the experiment name and fingerprint. A mismatch is an error unless you pass
   `--force`.
2. Skips done trials and runs the rest, continuing attempt numbers.
3. Counts earlier spend toward `budget_usd`.

To continue a run that stopped on budget, raise the budget and resume. `jobs`,
`budget_usd`, `keep_workspaces`, `workspace_root` and descriptions may change between
sessions. Forcing past a fingerprint change mixes two experiments in one analysis.

Records that do not belong to the current plan (for example arms or tasks no longer
selected) are ignored in the analysis, and the report says how many.

Ctrl-C kills running agents. Their attempts are not recorded and run again on resume. The
exit code is 130.

## Inspecting a run

```sh
agent-ab status runs/my-experiment-20260101-120000
agent-ab show runs/my-experiment-20260101-120000 fix-slugify__tdd__r2
agent-ab report runs/my-experiment-20260101-120000 --format md --out report.md
```

`report` can re-analyse with another `--baseline`, `--alpha` or `--seed` without rerunning
anything.
