# agent-ab

[![CI](../../actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

A/B tests for coding-agent setups: instruction files, skills, models, effort levels and prompts.

Changes to an agent setup are usually judged from a few runs, and single runs are noisy: the
same agent can pass a task once and fail it the next time. agent-ab runs the same tasks under
each configuration, each trial in a fresh workspace, and grades every trial with a hidden
check the agent never sees. It pairs the configurations task by task and reports the
pass-rate difference with a confidence interval and a p-value. When the data cannot separate
the configurations, it says "no detectable difference".

Runs on Linux, macOS and Windows. Python 3.11+, no runtime dependencies.

## Install

```sh
uv tool install agent-ab
# or
pipx install agent-ab
# or
pip install agent-ab
```

## Quick start

The demo uses the built-in `mock` adapter: no API key, no network, no cost. It runs 16 trials
and takes 10-20 seconds.

```sh
agent-ab init demo
cd demo
agent-ab run experiment.toml
```

Progress goes to stderr. The report goes to stdout:

```text
agent-ab report: demo
baseline control | 4 tasks | 16/16 trials completed | 0 errors | total cost $0.456 | alpha 0.05

Pass-rate difference vs control (95% CI, paired over tasks)
  with-guide vs control: +25.0 pts [0.0, +50.0], p=0.50 (Holm 0.50) -> no detectable difference;
      cost x1.32 [1.16, 1.43]; time x1.09 [0.87, 1.24]
      4 paired tasks: 2 better, 0 worse, 2 tied

Arms (* = baseline)
  arm         pass rate        95% CI  tasks  trials  errors  cost/trial  cost/pass  time
  ---------------------------------------------------------------------------------------
  control *       50.0%   12.5%-87.5%      4       8       0     $0.0245    $0.0491  0.6s
  with-guide      75.0%  50.0%-100.0%      4       8       0     $0.0325    $0.0433  0.6s

Flaky tasks (3; outcome varied across repeats)
  merge-intervals, parse-duration, roman-numerals

Notes
  - with-guide vs control: only 4 paired tasks. Intervals from few tasks tend to be too narrow;
    verdicts rely on the paired permutation test. With 4 paired tasks no result can reach p < 0.05
    (the smallest possible p is 0.125).
```

The run directory under `runs/` also gets `report.html`, `report.md` and `analysis.json`.

## How it works

1. Each trial is one (task, arm, repeat). An arm is one agent configuration.
2. For each trial, agent-ab creates a temporary workspace, copies in the task's `repo/`,
   applies the arm's `remove` and `overlay`, and snapshots it with git.
3. It runs the task's `setup` command, then the agent with the prompt and a timeout.
4. It records cost, tokens, turns and the agent's diff, and kills any processes the agent
   left behind.
5. It copies the task's hidden `checks/` over the workspace and runs the `check` command.
   Exit code 0 is a pass.
6. It appends the record to `trials.jsonl`, deletes the workspace, and, after the last
   trial, compares each arm with the baseline over paired tasks.

## Running a real experiment

Install and sign in to the agent CLI (`claude` or `codex`) first. Read [Safety](#safety).

A minimal `experiment.toml` that tests an instruction file with Claude Code:

```toml
name = "tdd-instructions"
tasks = ["tasks/*"]          # each match is a directory with a task.toml
repeats = 3
jobs = 2
budget_usd = 25.0
timeout_s = 1200

[agent]
adapter = "claude-code"
model = "sonnet"

[agent.options]
permission_mode = "bypassPermissions"
setting_sources = "project"  # ignore your user-level Claude Code settings
max_turns = 60

[[arms]]
name = "control"

[[arms]]
name = "tdd"
overlay = "arms/tdd"         # contains a CLAUDE.md that asks for a failing test first
```

Check the config, then check that every task fails without its solution and passes with it:

```sh
agent-ab validate experiment.toml
agent-ab validate experiment.toml --tasks
```

See the plan, then run:

```sh
agent-ab run experiment.toml --dry-run
agent-ab run experiment.toml
```

If the run stops (Ctrl-C, crash, budget), continue it:

```sh
agent-ab run experiment.toml --resume runs/tdd-instructions-20260101-120000
```

`agent-ab init` also writes `experiment.claude-code.toml`, a commented template. Task
format: [docs/tasks.md](docs/tasks.md). Codex and other agents:
[docs/adapters.md](docs/adapters.md).

## Reading results

- **Pass rate** is the mean over tasks of each task's pass fraction. Every task weighs the
  same.
- **Diff** is the arm's pass rate minus the baseline's, in percentage points, over tasks
  both arms completed. The 95% CI comes from resampling tasks.
- **p** is from a paired sign-flip permutation test over tasks. **Holm** adjusts it for
  comparing several arms with the baseline.
- The verdict is `better` or `worse` only when the Holm-adjusted p is below `alpha` and the
  CI excludes 0. Otherwise it is `no detectable difference`.
- "No detectable difference" does not mean "no difference". Read the CI: it is the range of
  effects the data is compatible with.
- More tasks help more than more repeats. Small effects need many tasks: a 10-point
  difference typically needs well over 100. Run `agent-ab power` to estimate how many tasks
  you need before spending money. See [docs/power.md](docs/power.md).

Details: [docs/statistics.md](docs/statistics.md).

## Safety

> [!CAUTION]
> agent-ab runs coding agents unattended, with full permissions by default.

- The built-in adapters default to modes that never ask for approval (for example
  `bypassPermissions` for Claude Code).
- The workspace is a temporary directory, not a sandbox. The agent can read and write
  anything your user account can, use your credentials, use the network, and read the
  hidden checks.
- Run experiments in a container or a disposable VM that holds only the API key the agent
  needs. [docs/safety.md](docs/safety.md) has a Dockerfile.
- Set `budget_usd` and per-trial limits (`max_budget_usd`, `max_turns`, `timeout_s`).
  Running trials finish after the budget is reached, so spend can exceed it by up to `jobs`
  trials.

## CLI

| Command | Purpose |
|---|---|
| `agent-ab init [DIR] [--force]` | Write the offline demo and a Claude Code template. |
| `agent-ab validate CONFIG [--tasks] [--jobs N] [--arms A,B] [--only GLOB]` | Check a config. `--tasks` checks each task fails before and passes after its solution. |
| `agent-ab run CONFIG [--out DIR \| --resume DIR] [--jobs N] [--repeats N] [--budget USD] [--arms A,B] [--only GLOB] [--dry-run] [--keep-workspaces] [--force] [--quiet]` | Run or resume an experiment and write the reports. |
| `agent-ab report RUN_DIR [--format text\|md\|json\|html] [--out FILE] [--baseline ARM] [--alpha A] [--seed S]` | Re-analyse a run. |
| `agent-ab status RUN_DIR` | Progress, errors and spend of a run. |
| `agent-ab show RUN_DIR TRIAL_ID` | One trial's record and artifact paths. |
| `agent-ab power [RUN_DIR] [--effect PTS,..] [--tasks N,..] [--repeats R,..] [--alpha A] [--sims N] [--seed S] [--format text\|md\|json]` | Estimate how many tasks you need before spending money. |

Exit codes: `0` success, `1` runtime failure or validation problems, `2` usage or
configuration error, `130` interrupted. Set `AGENT_AB_DEBUG=1` for tracebacks.

## Documentation

- [Configuration](docs/configuration.md)
- [Tasks](docs/tasks.md)
- [Adapters](docs/adapters.md)
- [Statistics](docs/statistics.md)
- [Power analysis](docs/power.md)
- [Run directory](docs/run-directory.md)
- [Safety](docs/safety.md)
- [Examples](examples/README.md)
- [Changelog](CHANGELOG.md), [Contributing](CONTRIBUTING.md), [Security](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).
