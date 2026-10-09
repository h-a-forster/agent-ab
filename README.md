# agent-ab

[![CI](../../actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Controlled A/B experiments for coding-agent setups: run the same tasks under each
configuration, grade them with hidden checks, and get a pass-rate difference with a
confidence interval.

## Why

Agent setups usually change on instinct. Someone adds an instruction file, installs a skill,
switches to a bigger model, raises the effort level, or tells the agent to write tests first,
and then judges the result from a handful of sessions. Claims about such changes are rarely
measured.

Single runs are noisy. The same agent on the same task can pass on one run and fail on the
next, so a few anecdotes can point either way. To tell whether a change helps, you need many
tasks, repeated runs, grading the agent cannot game, and statistics that account for how the
data was collected.

agent-ab does that:

- Runs every task under every configuration (an **arm**) in a fresh, isolated workspace.
- Repeats each task/arm pair as many times as you ask.
- Grades each trial with a **hidden check** that is copied in only after the agent finishes.
- Pairs the arms task by task and reports the pass-rate difference with a bootstrap
  confidence interval, a paired permutation test, and cost and time ratios.
- Says "no detectable difference" when the data does not support a conclusion.

It has no runtime dependencies beyond the Python standard library and runs on Linux, macOS
and Windows.

## Quick start

Install it (any one of these):

```sh
uv tool install agent-ab
```

```sh
pipx install agent-ab
```

```sh
pip install agent-ab
```

Run the offline demo. It uses the built-in `mock` adapter, so it needs no API key and no
network, and finishes in seconds:

```sh
agent-ab init demo
cd demo
agent-ab run experiment.toml
```

The run prints progress on stderr, then a text report. It also writes `report.html`,
`report.md` and `analysis.json` into the run directory under `runs/`.

To install from source, clone the repository and run this from its root:

```sh
pip install .
```

or, for development, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Example output

The following is **illustrative example output**. Exact layout and numbers depend on the
version and on your experiment.

```text
Experiment: tests-vs-no-tests   baseline: control   alpha: 0.05
Trials: 240/240 completed, 0 infrastructure errors, total cost $41.80

Arm        Pass rate (95% CI)    Trials  Errors  Cost/trial  Cost/pass  Mean time
control    62.5% (52.1-72.4)        120       0     $0.19      $0.30      94s
no-tests   55.0% (44.6-65.3)        120       0     $0.15      $0.27      71s

Comparison vs control (40 paired tasks)
Arm        Diff (95% CI)            p     p (Holm)  Cost ratio        Time ratio        Verdict
no-tests   -7.5 pts (-16.7, +1.7)  0.14  0.14      0.79 (0.70-0.89)  0.76 (0.66-0.87)  no detectable difference

Tasks better/worse/tied: 6 / 11 / 23
Flaky tasks (outcome varied across repeats): 14
Notes:
- only 40 paired tasks: intervals are wide
```

Read this as: dropping tests made runs about 20% cheaper and faster, and the pass rate may
have fallen by up to 17 points or risen by up to 2. The experiment cannot tell which. See
[How to read results](#how-to-read-results).

## Concepts

| Term | Meaning |
|---|---|
| **Task** | A directory with a `task.toml`: a prompt, optional starting files (`repo/`), hidden check files (`checks/`), a `check` command, and an optional reference `solution/`. See [docs/tasks.md](docs/tasks.md). |
| **Arm** | One agent configuration under test: adapter, model, effort, CLI args, environment, prompt prefix/suffix, and files to add (`overlay`) or delete (`remove`) in the workspace. |
| **Baseline** | The arm every other arm is compared against. Defaults to the first arm. |
| **Repeat** | Each task runs `repeats` times per arm, because agents are not deterministic. |
| **Trial** | One (task, arm, repeat) cell. A trial can have several **attempts** if infrastructure errors force retries; the last attempt counts. |
| **Hidden check** | The command that grades a trial. Exit code 0 is a pass. Files in `checks/` are copied into the workspace only after the agent finishes, so the agent never sees them. |
| **Infrastructure error** | A failure unrelated to the configuration under test (authentication, rate limit, provider outage, setup failure). Retried up to `max_retries` times, then excluded from statistics and reported. |

Each trial runs like this:

1. Create a temp workspace, copy in the task's `repo/`, apply the arm's `remove` and
   `overlay`, and snapshot it with git.
2. Run the task's `setup` command, if any.
3. Build the prompt (arm prefix, task prompt, arm suffix) and launch the agent with a
   wall-clock timeout.
4. Record cost, tokens, turns and the diff the agent made.
5. Copy `checks/` into the workspace and run the `check` command.
6. Append a record to `trials.jsonl` and delete the workspace.

## A real experiment with Claude Code

This walkthrough tests whether an instruction file that says "write a failing test first"
changes the pass rate on your own tasks. It assumes the `claude` CLI is installed and
authenticated.

> [!WARNING]
> Real agents run unattended with full permissions. Read [Safety](#safety) first and run
> experiments inside a container or VM.

`agent-ab init` writes a commented template, `experiment.claude-code.toml`, next to the demo.
A minimal version looks like this:

```text
my-experiment/
  experiment.toml
  arms/
    tdd/
      CLAUDE.md          # "Before changing code, write a failing test that reproduces the issue."
  tasks/
    fix-slugify/
      task.toml
      repo/              # starting files
      checks/            # hidden tests
      solution/          # optional reference fix
    parse-dates/
      ...
```

```toml
name = "tdd-instructions"
tasks = ["tasks/*"]
repeats = 3
jobs = 2
budget_usd = 25.0
timeout_s = 1200

[agent]
adapter = "claude-code"
model = "sonnet"
effort = "medium"

[agent.options]
permission_mode = "bypassPermissions"
# Load only settings from the workspace, so your personal configuration
# does not leak into either arm.
setting_sources = "project"
max_turns = 60

[[arms]]
name = "control"
description = "No instruction file"

[[arms]]
name = "tdd"
description = "CLAUDE.md asking for a failing test first"
overlay = "arms/tdd"
```

Check the configuration and the tasks before spending money:

```sh
agent-ab validate experiment.toml
agent-ab validate experiment.toml --tasks
```

`--tasks` runs each hidden check on the untouched starting files (it must fail) and on the
starting files plus `solution/` (it must pass). Fix every task it flags.

See what would run, then run it:

```sh
agent-ab run experiment.toml --dry-run
agent-ab run experiment.toml
```

Progress lines look like this (illustrative):

```text
[ 12/60] fix-slugify  tdd  r2  pass   41.2s  $0.31  (spent $3.10)
```

If the run stops (Ctrl-C, a crash, the budget), continue it in the same run directory:

```sh
agent-ab run experiment.toml --resume runs/tdd-instructions-20260101-120000
```

Inspect results at any time:

```sh
agent-ab status runs/tdd-instructions-20260101-120000
agent-ab report runs/tdd-instructions-20260101-120000 --format html --out report.html
agent-ab show runs/tdd-instructions-20260101-120000 fix-slugify__tdd__r2
```

Other adapters work the same way: `codex` for the Codex CLI, and `command` for any agent you
can start from a command line. See [docs/adapters.md](docs/adapters.md).

## How to read results

**Pass rate** for an arm is the mean, over tasks, of the fraction of that task's trials that
passed. Every task counts equally regardless of how many trials completed.

**Diff (95% CI)** is the arm's pass rate minus the baseline's, in percentage points, over the
tasks both arms completed. The interval comes from resampling tasks (a cluster bootstrap). It
is the range of effects compatible with your data: if it runs from -16.7 to +1.7, a drop of
15 points and a gain of 1 point are both plausible.

**p** is from a paired sign-flip permutation test over tasks. It answers: if the arm made no
difference, how often would a per-task difference this large appear by chance? **p (Holm)**
corrects for comparing several arms against the baseline.

**Verdict** is `better` or `worse` only when the Holm-adjusted p is below `alpha` *and* the
interval excludes zero. Otherwise it is `no detectable difference`, or `insufficient data`
with fewer than two paired tasks.

**"No detectable difference" is not "no difference".** It means this experiment was too
small or too noisy to distinguish the arms. Look at the interval: a narrow one around zero
is evidence that any effect is small; a wide one means you have not learned much yet.

**Cost and time ratios** compare per-task mean cost and agent duration (arm / baseline). A
ratio of 0.79 means the arm cost about 21% less.

### How many tasks and repeats you need

The unit of evidence is the **task**, not the trial. Repeats reduce noise within a task, but
they cannot tell you how an arm behaves on tasks you did not include. More tasks almost
always buy more than more repeats.

A rough rule of thumb, using one trial per task per arm: the per-task difference is -1, 0 or
+1. If a fraction `q` of tasks are discordant (pass in one arm, fail in the other) and the
true difference is `d`, the variance of the per-task difference is about `q - d²`. For 80%
power at a two-sided 5% level you need roughly

```text
n ≈ (1.96 + 0.84)² × (q − d²) / d²  ≈  7.84 × (q − d²) / d²
```

paired tasks. Some values:

| True difference `d` | Discordant fraction `q` | Paired tasks needed |
|---|---|---|
| 20 points | 0.30 | about 50 |
| 10 points | 0.20 | about 150 |
| 10 points | 0.30 | about 230 |
| 5 points | 0.20 | about 600 |

So detecting a 10-point change takes on the order of a hundred-plus paired tasks; 20 tasks
will only catch very large effects. With several repeats, each task contributes a
difference of pass fractions instead of -1/0/+1, which removes some trial-level noise, so the
numbers above are on the conservative side; they do not shrink much below them, because
tasks genuinely differ. Three repeats is a reasonable default. More detail in
[docs/statistics.md](docs/statistics.md).

## Safety

> [!CAUTION]
> agent-ab launches coding agents unattended. The adapters' defaults give them full
> permissions (for example `bypassPermissions` for Claude Code), because nobody is there to
> approve tool calls.

- The workspace is a **temporary directory, not a sandbox**. An agent can read and write
  anything your user account can, including your home directory, SSH keys and cloud
  credentials, and it can use the network. It could also read the task directories,
  including hidden checks.
- **Run experiments inside a container or a disposable VM** with only the credentials the
  agent needs. [docs/safety.md](docs/safety.md) has a minimal Dockerfile.
- **Set a budget.** `budget_usd` stops scheduling new trials once recorded spend reaches it.
  Trials already running finish, so actual spend can exceed the budget by up to `jobs`
  trials. Per-trial limits such as `max_budget_usd` and `max_turns` (Claude Code) bound each
  trial.
- Task prompts and repositories are input to an agent with full permissions. Do not run task
  suites you have not read.

## CLI reference

```text
agent-ab [--version] <command> ...
```

| Command | Purpose |
|---|---|
| `agent-ab init [DIR] [--force]` | Scaffold an offline demo (mock adapter, 4 tasks, 2 arms) and a commented `experiment.claude-code.toml` template. |
| `agent-ab validate CONFIG [--tasks] [--arms a,b] [--only GLOB]` | Load and check a config; print tasks, arms, planned trials and adapter availability. `--tasks` checks each task fails before and passes after its solution. |
| `agent-ab run CONFIG [options]` | Run an experiment, print the text report, write `report.html`, `report.md` and `analysis.json` into the run directory. |
| `agent-ab report RUN_DIR [--format text\|md\|json\|html] [--out FILE] [--baseline ARM] [--alpha A] [--seed S]` | Re-analyse a run directory. |
| `agent-ab status RUN_DIR` | Progress, errors, spend and last activity of a run. |
| `agent-ab show RUN_DIR TRIAL_ID` | One trial's record and the paths to its artifacts. |

`run` options:

| Option | Meaning |
|---|---|
| `--out DIR` | Run directory (default `runs/<name>-<UTC timestamp>` next to the config). |
| `--resume DIR` | Continue an existing run; completed trials are skipped. |
| `--jobs N` | Concurrent trials (overrides `jobs`). |
| `--repeats N` | Repeats per task and arm (overrides `repeats`; part of the fingerprint). |
| `--budget USD` | Spend limit (overrides `budget_usd`). |
| `--arms a,b` | Run only these arms. The baseline must be included. |
| `--only GLOB` | Run only tasks whose id matches the glob. |
| `--dry-run` | Plan and print; create nothing, run nothing. |
| `--keep-workspaces` | Keep each trial's workspace for inspection. |
| `--force` | Resume even if the configuration fingerprint changed. |
| `--quiet` | No progress lines. |

Exit codes: `0` success, `1` runtime failure or validation problems, `2` usage or
configuration error, `130` interrupted with Ctrl-C. Errors are printed as
`agent-ab: error: <message>`; set `AGENT_AB_DEBUG=1` for a traceback.

Full configuration reference: [docs/configuration.md](docs/configuration.md).

## FAQ

**Why not just run each setup once or twice and compare?**
Because a single trial is a coin flip with an unknown bias. On a task the agent solves 60% of
the time, two runs disagree almost half the time. Differences you see across a few runs are
mostly noise. agent-ab pairs arms on the same tasks and tells you how large the noise is.

**Does it work with agent X?**
Yes, if X can run non-interactively from a command line. Use the `command` adapter with an
argv template; optionally have your wrapper write `usage.json` so cost and tokens are
recorded. Claude Code and Codex have built-in adapters. See
[docs/adapters.md](docs/adapters.md).

**Does it run on Windows?**
Yes. Use argv lists and `{python}` in task commands instead of shell strings, so checks run
the same on every platform. Process trees are killed with `taskkill` on timeout.

**How do I control cost?**
Set `budget_usd` (or `--budget`), use adapter limits such as `max_budget_usd` and `max_turns`,
start with `--dry-run` to see the trial count, and run a small pilot with `--only` and
`--repeats 1` before the full experiment. The mock adapter lets you test the whole pipeline
for free.

**Is a run reproducible, and can I resume it?**
Agents are not deterministic, so outcomes are not reproducible. What is fixed: the trial
order (shuffled from `seed`), each trial's seed, and the analysis (bootstrap and permutation
draws use `--seed`). Each run stores a fingerprint of the resolved configuration and the
contents of every task and overlay file. `--resume` refuses to continue if the fingerprint
changed, so one run never mixes two experiments. `jobs`, `budget_usd`, `keep_workspaces`,
`workspace_root` and `description` are excluded from the fingerprint and may change between
sessions. See [docs/run-directory.md](docs/run-directory.md).

**Can a trial "pass" by editing the tests?**
The hidden `checks/` files are copied in after the agent finishes and overwrite whatever the
agent wrote at those paths. Put everything the check depends on in `checks/`.

## Documentation

- [Configuration reference](docs/configuration.md)
- [Writing tasks](docs/tasks.md)
- [Adapters](docs/adapters.md)
- [Statistics](docs/statistics.md)
- [Run directory and records](docs/run-directory.md)
- [Safety](docs/safety.md)
- [Changelog](CHANGELOG.md), [Contributing](CONTRIBUTING.md), [Security](SECURITY.md)

## License

MIT. See [LICENSE](LICENSE).
