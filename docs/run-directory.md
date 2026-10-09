# Run directory and records

Every `agent-ab run` writes into one run directory. By default it is
`runs/<name>-<UTC YYYYmmdd-HHMMSS>` next to the experiment file; choose another with
`--out DIR`. The directory is self-contained: `report`, `status` and `show` need only the
run directory, not the original configuration.

## Layout

```text
<run_dir>/
  run.json                 run metadata and the resolved configuration
  trials.jsonl             one record per attempt, append-only
  trials/
    <trial_id>/
      attempt-<n>/
        prompt.md          the exact prompt sent to the agent
        agent.stdout       agent output
        agent.stderr
        setup.*            setup command output (if the task has setup)
        check.stdout       hidden check output
        check.stderr
        diff.patch         the agent's changes (binary git diff against the starting snapshot)
        usage.json         usage written by the agent (command and mock adapters)
        record.json        this attempt's record
        workspace.txt      kept workspace path (only with keep_workspaces)
  report.html              written at the end of `run`
  report.md
  analysis.json
```

Files that do not apply to an attempt are absent: an attempt that failed during setup has no
agent output, and an agent timeout with `timeout_is_failure = true` has no check output.

The trial id is `<task>__<arm>__r<repeat>`, with `repeat` counting from 0, for example
`fix-slugify__tdd__r2`. Attempts count from 0.

## `run.json`

| Field | Meaning |
|---|---|
| `schema` | Run directory schema version (currently `1`). |
| `tool` | `"agent-ab"`. |
| `version` | agent-ab version that created the run. |
| `experiment` | Experiment name. |
| `fingerprint` | Fingerprint of configuration and task/overlay contents (see [configuration.md](configuration.md#fingerprint)). |
| `created_at` | Creation time, ISO-8601 UTC. |
| `config` | The resolved configuration: every arm with defaults merged, every task. |
| `planned_trials` | Number of (task, arm, repeat) trials planned. |
| `seed` | Experiment seed. |
| `baseline` | Baseline arm name. |

## `trials.jsonl`

One JSON object per line, one line per **attempt**. Lines are only ever appended, and each
is flushed to disk as it is written, so a crash loses at most the attempt in progress. A
truncated last line (from a crash mid-write) is ignored when the file is read; corruption
elsewhere is an error.

A trial may have several lines when infrastructure errors forced retries. The line with the
highest `attempt` is the trial's result.

### Record fields

| Field | Type | Meaning |
|---|---|---|
| `trial_id` | string | `<task>__<arm>__r<repeat>`. |
| `task` | string | Task id. |
| `arm` | string | Arm name. |
| `repeat` | integer | Repeat index, from 0. |
| `attempt` | integer | Attempt index, from 0. |
| `status` | `"pass"`, `"fail"`, `"error"` | `error` is an infrastructure error, excluded from statistics. |
| `passed` | boolean or null | Check outcome; null when no outcome was determined. |
| `agent_exit_code` | integer or null | Agent exit code; null if it could not start or was killed. |
| `agent_timed_out` | boolean | The agent hit its time limit. |
| `check_exit_code` | integer or null | Hidden check exit code; null if the check did not run. |
| `check_timed_out` | boolean | The check hit its time limit (counts as fail). |
| `duration_s` | number or null | Agent wall-clock time in seconds. |
| `check_duration_s` | number or null | Check wall-clock time in seconds. |
| `cost_usd` | number or null | Cost reported by the adapter. |
| `input_tokens` | integer or null | Input tokens. |
| `output_tokens` | integer or null | Output tokens. |
| `cache_read_tokens` | integer or null | Cached input tokens read. |
| `cache_write_tokens` | integer or null | Tokens written to a cache. |
| `turns` | integer or null | Agent turns. |
| `files_changed` | integer or null | Files changed by the agent; null when git is unavailable. |
| `lines_added` | integer or null | Lines added by the agent. |
| `lines_removed` | integer or null | Lines removed by the agent. |
| `error` | string or null | Error description for `error` attempts (and other diagnostic text). |
| `started_at` | string or null | Start time, ISO-8601 UTC. |
| `finished_at` | string or null | End time, ISO-8601 UTC. |
| `artifacts` | string or null | Attempt directory, relative to the run directory, with forward slashes. |
| `schema` | integer | Record schema version (currently `1`). |

`null` always means "unknown", never zero. Statistics skip unknown values; for example, an
arm whose trials report no cost gets no cost estimate rather than a cost of zero.

Example (one line, wrapped here for reading):

```json
{"trial_id": "fix-slugify__tdd__r2", "task": "fix-slugify", "arm": "tdd", "repeat": 2,
 "attempt": 0, "status": "pass", "passed": true, "agent_exit_code": 0,
 "agent_timed_out": false, "check_exit_code": 0, "check_timed_out": false,
 "duration_s": 41.2, "check_duration_s": 1.3, "cost_usd": 0.31, "input_tokens": 18234,
 "output_tokens": 2210, "cache_read_tokens": 90112, "cache_write_tokens": 10240,
 "turns": 14, "files_changed": 2, "lines_added": 31, "lines_removed": 4, "error": null,
 "started_at": "2026-01-01T12:03:10Z", "finished_at": "2026-01-01T12:03:53Z",
 "artifacts": "trials/fix-slugify__tdd__r2/attempt-0", "schema": 1}
```

The JSONL format is easy to load elsewhere:

```python
import json
from pathlib import Path

rows = [json.loads(line) for line in Path("trials.jsonl").read_text("utf-8").splitlines() if line]
```

Remember to keep only the last attempt per `trial_id` before computing anything.

## When is a trial done?

A trial is **done** when its last attempt has status `pass` or `fail`, or has status `error`
and `attempt >= max_retries` (retries exhausted). Done trials are never rerun.

## Resume

```sh
agent-ab run experiment.toml --resume runs/my-experiment-20260101-120000
```

Resuming:

1. Opens the run directory and compares the experiment name and fingerprint with the
   current configuration. A mismatch stops with an error, unless you pass `--force`.
2. Skips done trials.
3. Runs the remaining trials, including retries of trials whose last attempt was an error
   with retries left. Attempt numbers continue from the last recorded attempt.
4. Counts spend from earlier sessions toward `budget_usd`.

You can change `jobs`, `budget_usd`, `keep_workspaces`, `workspace_root` and `description`
between sessions without affecting the fingerprint. Raising the budget and resuming is the
normal way to continue a run that stopped on budget.

Changing anything else (tasks, checks, overlays, arms, `repeats`, `max_retries`, agent
settings) changes the fingerprint. Forcing a resume in that case mixes trials from two
different experiments in one analysis; do it only if you understand what changed and why it
does not matter.

Ctrl-C stops the run: running agents are killed and their attempts are not recorded, so
they run again on resume. The command exits with code 130.

## Inspecting a run

```sh
agent-ab status runs/my-experiment-20260101-120000
agent-ab show runs/my-experiment-20260101-120000 fix-slugify__tdd__r2
agent-ab report runs/my-experiment-20260101-120000 --format md --out report.md
```

`report` can recompute the analysis with a different baseline (`--baseline`),
significance level (`--alpha`) or analysis seed (`--seed`) without rerunning anything.
