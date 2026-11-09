# Run directory

Each `agent-ab run` writes one run directory. The default is
`runs/<name>-<UTC YYYYmmdd-HHMMSS>` next to the experiment file; `--out DIR` sets another.
`--out` refuses a directory that already contains a run or leftover `trials.jsonl` or
`trials/`. `report`, `status` and `show` need only the run directory.

One session runs in a run directory at a time; a second `run` or `--resume` is refused before
anything runs. The lock is an operating-system lock on `run.lock`, released when the process
ends however it ends, so a crash leaves nothing to clear. On a network filesystem it is only as
good as that filesystem's locking. `report`, `status`, `show` and `--dry-run` do not take it.

## Layout

```text
<run_dir>/
  run.json                 metadata and the resolved configuration
  run.lock                 who holds the session lock (a leftover file is harmless)
  workspaces-in-use/       one list per attempt of the directories it created outside the run
                           directory; what stays after a session was left behind
  trials.jsonl             one record per attempt, append-only
  trials/<trial_id>/attempt-<n>/
    prompt.md              prompt sent to the agent
    agent.stdout, agent.stderr
    setup.stdout, setup.stderr      if the task has setup
    check.stdout, check.stderr
    check-report.json      outcome recorded by the verifying unittest runner
    grade-setup.stdout, grade-setup.stderr   setup of the grading copy, if the task has setup
    control-*              grading repeated on an untouched copy, after a grading step failed
    diff.patch             the agent's changes (git diff against the starting snapshot)
    init.json              the agent's scrubbed init event (claude-code, capture_init)
    usage.json             usage written by the agent (command and mock adapters)
    record.json            this attempt's record
    workspace.txt          kept workspace path (keep_workspaces only)
    grade-workspace.txt    kept grading-copy path (keep_workspaces only)
  report.html, report.md, analysis.json     written at the end of run
```

Files that do not apply are absent. Some adapters and failure paths add more, for example
`append_system_prompt.md` (claude-code), `traceback.txt` or `workspace-leaked.txt` (one
line per workspace that could not be deleted).

The trial id is `<task>__<arm>__r<repeat>`, for example `fix-slugify__tdd__r2`. Repeats and
attempts count from 0.

## `run.json`

| Field | Meaning |
|---|---|
| `schema` | Schema version (`1`). |
| `tool`, `version` | `"agent-ab"` and the version that created the run. |
| `experiment` | Experiment name. |
| `fingerprint` | See [configuration.md](configuration.md#fingerprint). |
| `fingerprint_scheme` | Version of the fingerprint recipe (currently `2`). A mismatch on resume is reported as a format change rather than an edited experiment; runs without it use scheme `1`. |
| `created_at` | ISO-8601 UTC. |
| `config` | Resolved configuration. `env` values are replaced by `"<redacted>"`; names are kept. |
| `planned_trials` | Number of planned trials. |
| `seed`, `baseline` | Experiment seed and baseline arm. |
| `grading` | How trials are graded: `clean-copy`, or `agent-workspace` without git on the host. Absent in runs from before it was recorded; resuming those needs `--force`. |
| `forced_resumes` | One entry per `--force` that got past a difference: `at`, `changed`, `version`, `from_fingerprint`, `from_grading`. Absent if there was none. |
| `agent_versions` | Object mapping arm name to the agent CLI version probed at the start of the session (`<executable> --version`). Absent when no adapter could tell; refreshed on resume. |

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
| `concurrency` | integer or null | Number of trials in flight when this attempt started, itself included. Useful when judging whether load affected durations. |
| `models` | array of strings or null | Model IDs the agent reported using, sorted (claude-code: keys of `modelUsage`). |
| `agent_version` | string or null | Agent CLI version: the one the agent reported during the trial if it did, else the per-arm probe. |
| `agent_init` | object or null | Compact summary of the agent's init event: `model`, `claude_code_version`, `permission_mode`, `api_key_source`, and names of `tools`, `mcp_servers`, `plugins`, `skills`, `agents`; `config_leaks` lists memory or instruction files loaded from outside the workspace ([isolation](adapters.md#isolation)). |
| `prompt_sha256` | string or null | SHA-256 (hex) of the UTF-8 prompt text sent to the agent: `prompt.md` without its final newline. Null for attempts that ended before the agent was built. |
| `isolation_breach` | boolean | The agent loaded configuration from outside its isolation. Such an attempt is not retried, uses no retries, stays open for `--resume`, and three with no graded trial of their arm since stop the run ([isolation](adapters.md#isolation)). |
| `instructions_sha256` | object or null | SHA-256 of a fixed set of instruction files. The workspace files `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md` and `AGENTS.md`, hashed after setup, are keyed by relative path; files an adapter passes from outside the workspace are keyed `agent:<name>` (claude-code: `agent:append_system_prompt.md`). Null when there are none. Not covered: other workspace files agents read (`.claude/rules/`, skills, agents and settings under `.claude/`, `CLAUDE.md` in subdirectories, Codex's `AGENTS.override.md`), and user-level and parent-directory instruction files (such as `~/.claude/CLAUDE.md`), which the agent may still load unless the arm restricts its setting sources. Arms that differ only in uncovered files hash as identical. |
| `leak_check` | string or null | `clean`, `leaked`, or `unverified` when nothing could be checked (no usable init event, the check or parser crashed, `capture_init = false`). Null for adapters with no check and older records. The report counts unverified trials. |
| `tool_version`, `fingerprint` | string or null | agent-ab version and experiment fingerprint this attempt ran under. Null in older records. |
| `grading` | string or null | `clean-copy` or `agent-workspace`. Null if it was never graded, and in older records. |
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
up. Isolation breaches use no retries and leave the trial open. Resuming:

1. Checks the experiment name, fingerprint, grading mode and agent-ab version. A mismatch, or a
   run that did not record its grading mode, is an error unless you pass `--force`.
2. Removes workspaces listed in `workspaces-in-use/` that earlier sessions left behind.
3. Skips done trials and runs the rest, continuing attempt numbers.
4. Counts earlier spend toward `budget_usd`.

To continue a run that stopped on budget, raise the budget and resume. `jobs`,
`budget_usd`, `keep_workspaces`, `workspace_root` and descriptions may change between
sessions.

`--force` past a difference mixes trials from both sides in one analysis. `run.json` then takes
on the forced experiment (plan, baseline, `max_retries`), adds an entry to `forced_resumes`, and
the report says how many trials ran under an earlier definition.

Records that do not belong to the current plan (for example arms or tasks no longer
selected with `--force`) are ignored in the analysis and `status`, and the report says how many
and what they cost.

To try trials again whose retries ran out, once the cause is fixed:

```sh
agent-ab run experiment.toml --resume runs/my-experiment-20260101-120000 --retry-errors
```

Each gets a fresh set of `max_retries` retries, continuing its attempt numbers. Passes, fails and
everything in the log stay; no `--force` is involved.

Ctrl-C kills running agents. Their attempts are not recorded and run again on resume; attempts
that had already finished are kept. The exit code is 130.

## Inspecting a run

```sh
agent-ab status runs/my-experiment-20260101-120000
agent-ab show runs/my-experiment-20260101-120000 fix-slugify__tdd__r2
agent-ab report runs/my-experiment-20260101-120000 --format md --out report.md
```

`report` can re-analyse with another `--baseline`, `--alpha` or `--seed` without rerunning
anything.
