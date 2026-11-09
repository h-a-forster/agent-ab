# AGENTS.md

Guide for coding agents (and humans) working on agent-ab. User-facing docs are in `README.md`
and `docs/`; contributor rules are in `CONTRIBUTING.md`.

## What this is

A CLI and library that runs A/B experiments on coding-agent setups (instruction files,
models, prompts): each trial in a fresh workspace, graded by hidden checks in a clean copy,
analysed with paired task-level statistics. Example results for Claude Code are in
`docs/results.md` and `docs/results/`.

## Conventions

- uv + hatchling, `src/` layout, Python >= 3.11, standard library only at runtime, `ruff
  check` + `ruff format` (line length 100), pytest. `examples/tasks/` is excluded from ruff:
  the task repos contain deliberate bugs.
- Shared types live in `src/agent_ab/model.py`, errors in `src/agent_ab/errors.py`, adapters
  in `src/agent_ab/adapters/` (registered in `_REGISTRY`).
- Tests run offline and fast: `mock` adapter or a fake agent started with `sys.executable`,
  files only under `tmp_path`, no `sh` assumptions (CI runs Linux, macOS and Windows,
  Python 3.11-3.13).
- Every example task must fail before and pass after its `solution/`
  (`agent-ab validate ... --tasks`). Changing a task's prompt or checks changes what
  published results mean: note it in `CHANGELOG.md` and `docs/results.md`.
- Results in `docs/results/<run>/` are the run's own `run.json`, `trials.jsonl`, reports and
  `manipulation.jsonl`, plus a copy of the config. Per-trial artifacts (`trials/`) are not
  committed. Every number in `README.md` and `docs/results.md` must trace to these files.
- Real-agent runs spend money and run with full permissions: never inside the test suite;
  set `budget_usd`; use a resumable launcher for anything long.
- User-visible changes get a `CHANGELOG.md` entry under "Unreleased".
- Scratch files go in `tmp/` (gitignored). No `.bak` copies; use git.
- The repository is public: change it through pull requests with CI, not direct pushes to
  `main`.
- Public-release hygiene: no personal names, local user paths or machine details in
  committed files, results or logs.

## How to test

```sh
uv sync --group dev
uv run pytest                 # offline, a few minutes
uv run ruff check .
uv run ruff format --check .
uv run agent-ab validate examples/quickstart/experiment.toml --tasks
```

CI (`.github/workflows/ci.yml`) also builds the wheel and runs the offline demo from it.

## Status

Updated: 2026-11-06 (v0.1.1 prepared on branch `polish-2026-10-30`, not tagged; trial isolation
added after it, unreleased, notes in `docs/release-notes-0.2.0.md`). Open work is in
`backlog.md`.

- v0.1.0 (2026-10-10); since then clean-copy grading, verified unittest outcomes, model and
  CLI-version recording, 40 more example tasks, and four example runs (two calibration
  pilots, the 50-task x 3-repeat no-tests experiment, Haiku 5.5 vs Sonnet 5.5).
- Headline numbers in `README.md` and `docs/results.md` re-checked against the committed
  reports and `manipulation.jsonl` files on 2026-11-06; `agent-ab report` reproduces every
  committed `report.md` byte for byte.
- The no-tests experiment re-run on 2026-10-30 with the current grader and Claude Code 2.1.308
  (`docs/results/haiku-5-5-no-tests-rerun`). Its pass-rate headline replicated under a
  contaminated control: both arms loaded the machine's user-level CLAUDE.md, so it is not a
  clean replication and its tests-written, cost and time comparisons are confounded.
- Trial isolation for `claude-code` (unreleased, on by default): empty `CLAUDE_CONFIG_DIR` per
  trial, allow-listed environment, workspaces outside the home directory, a pre-run check of
  the workspace root's parents, and a leak check of the raw init event
  (`docs/adapters.md#isolation`). Checked against the real CLI without a credential, not yet
  in an authenticated trial.
- Not published to PyPI; install is from GitHub.
