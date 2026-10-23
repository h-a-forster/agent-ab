# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This
project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- 40 example tasks (50 in total): 20 round-1 tasks, 10 bug hunts and 10 large features.
- `claude-code` options `capture_init` and `strict_mcp_config`, both on by default.
- Per trial: the models actually used, the CLI version and a scrubbed summary of the agent's
  init event (saved as `init.json`); reports show them per arm and flag differences.
- Per-trial record of how many trials were in flight at its start.
- Per trial: `prompt_sha256` (the exact prompt sent) and `instructions_sha256` (workspace
  instruction files such as `CLAUDE.md` and `AGENTS.md`, and adapter files such as the
  claude-code system-prompt file), next to the CLI version.
- One-arm runs, for pilots that measure baseline difficulty.
- Manipulation check script, `docs/results/manipulation.py`.

### Changed

- `run.json` stores paths relative to the run directory, and the configuration fingerprint no
  longer depends on where the repository sits. The scheme changed, so resume older runs with
  `--force`.
- `claude-code` now requests `stream-json` output by default (needed for the init event).
- Trials are shuffled by (task, repeat) block, with the arms of a block adjacent and in random
  order.
- `examples/quickstart/experiment.toml` lists the ten original tasks explicitly.
- `power` handles negative effects, reports when there is no headroom, uses a non-degenerate
  false-positive check and searches a finer grid.
- CI actions bumped: checkout v7, setup-uv v10.3.0, upload-artifact v7.

### Fixed

- Grading runs in a clean copy: a fresh workspace from the pristine task (arm files and task
  setup included) with only the agent's recorded diff applied and the hidden checks on top.
  Files outside the diff (interpreter caches such as a forged `.pyc`, a tampered `.git`) no
  longer reach the checks. A trial whose diff cannot be recorded or applied fails. Setup now
  runs twice per trial; new artifacts `grade-setup.*`, `grade-workspace.txt`.
- Diff recording tells its failures apart: a missing or replaced `.git` fails the trial as
  tampering, a git error fails it with git's message, and a `diff.patch` that cannot be written
  is an infrastructure error. Nested git repositories, whether the agent or the task's setup
  creates them, are recorded as plain files (in the setup baseline and in the agent's diff)
  instead of a gitlink that hides edits inside them, and a stale `.git/index.lock` is removed
  before the diff. `diff_stats` now raises (`GitDirAlteredError`, `WorkspaceError`, `OSError`)
  instead of returning None for these cases.
- `run_check` resolves a relative `report_path` before handing it to the check, which runs in
  the workspace.
- Argv checks of the form `{python} -m unittest ...` run under a verifying runner
  (`agent_ab.checkrun`) that records the outcome out of band with a one-time nonce
  (`check-report.json`). Agent code that forces the exit status (an `atexit` hook calling
  `os._exit(0)`, `sys.exit(0)` at import, `SkipTest` at import) no longer fakes a pass. Skipped
  hidden tests and runs with no tests now count as failures.
- `feature-uri-resolve`: the hidden oracle and the reference solution lowercased percent-encoding
  hex digits in a host, contradicting the prompt (and RFC 3986 section 6.2.2.1). They now keep
  them uppercase, and the check has an explicit case. Published results predate the fix.
- Hardened grading: checks run with `PYTHONSAFEPATH=1`, and check-only paths are cleared before
  checks are installed, so agent-planted files cannot shadow the standard library or add tests.
- `run.json` no longer leaks absolute home-directory paths.

## 0.1.0 - 2026-10-10

Initial release.

- TOML experiment config: tasks, arms with per-arm agent overrides, prompt prefix/suffix,
  workspace overlays and removals, repeats, concurrency, timeouts, retries, budget. Unknown
  keys are errors.
- Task format: prompt, starting files, hidden checks applied after the agent finishes,
  optional setup and reference solution. `{python}` and `{workspace}` placeholders.
- Fresh temporary workspace per trial, snapshotted with git to record the agent's diff.
  Leftover agent processes are killed after each trial.
- Adapters: `claude-code`, `codex`, `command` (any agent, `usage.json` for cost and tokens)
  and `mock` (offline).
- Infrastructure-error detection with retries; errored trials are excluded and reported.
- Run directory with `run.json`, append-only `trials.jsonl` and per-attempt artifacts.
  Resume with a configuration fingerprint check and repair of a truncated last log line.
- Statistics: task-level pass rates with cluster-bootstrap intervals, paired differences,
  paired sign-flip permutation test, Holm correction, cost and time ratios, flaky-task
  detection.
- Reports in text, Markdown, JSON and HTML.
- Commands: `init`, `validate` (with fail-before/pass-after task checks), `run`, `report`,
  `status`, `show`, `power`.
- Linux, macOS and Windows; Python 3.11-3.13; no runtime dependencies.
- Example results: Claude Code (Haiku, Sonnet) with and without tests on the example tasks
  (`docs/results.md`).
