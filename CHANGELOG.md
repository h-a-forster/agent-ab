# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This
project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- `claude-code` option `isolation`, on by default: each trial gets an empty
  `CLAUDE_CONFIG_DIR` beside its workspace (removed after the agent exits) and an allow-listed
  environment (option `pass_env` adds names), and the raw init event is checked for memory or
  instruction files loaded from outside the workspace. Leaks are recorded in
  `agent_init.config_leaks`, make the attempt an infrastructure error, and are noted in the
  report. A run refuses to start when `CLAUDE.md`, `AGENTS.md` or similar files exist in the
  workspace root or its parents, or when no credential is set in the environment.
- Adapter hook `check_workspace_root`, and `AgentInvocation.base_env` and `temp_dirs`.
- `agent-ab run --resume DIR --retry-errors` runs trials whose retries ran out again, with fresh
  retries, keeping everything recorded.
- A lock on the run directory: a second session is refused before anything runs. It is released
  when the process ends, so a crash leaves nothing stale.
- Trial records gain `leak_check` (`clean`, `leaked`, `unverified`), `tool_version`, `fingerprint`
  and `grading`; `run.json` gains `grading` and `forced_resumes`. All optional on read.
- A run stops after ten infrastructure errors in a row in one arm, before an outage uses up every
  trial's retries.

### Changed

- `claude-code` no longer uses your saved login by default: set `ANTHROPIC_API_KEY` or
  `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`), or set `isolation = false`.
- Resuming is refused unless forced when the agent-ab version or grading mode differs, or the run
  recorded no grading mode, as with runs from 0.1.1: they would mix grading or isolation settings
  with nothing to show for it. To keep such a run as it was, set `isolation = false`, which
  changes the configuration, and resume with `--force`.
- A forced resume now updates the plan in `run.json` and is noted in the report. Trials added by
  `--repeats` count; trials no longer selected are left out of the analysis and `status`.
- A grading failure the machine caused (full disk, no memory, a moved `checks/` folder, a broken
  check command) is an infrastructure error, retried and excluded, not a final `fail`. Sabotage of
  the agent's own workspace still fails.
- `claude-code`: a failed result counts against the agent only for a turn or budget limit or a
  status that blames the request, whatever its text says, and a CLI that dies with no result is an
  infrastructure error. A parser crash means usage unknown.
- An isolation breach leaves the trial open everywhere: not counted as an error by `run`, exit code
  1 with a resume hint, and no retries used. The three-breach stop counts per arm and across
  sessions. The report counts open trials as unfinished.
- Attempts that finished before Ctrl-C are kept. A stale attempt folder that cannot be removed is
  not reused. `run.json` is synced to disk before it replaces the old one. Experiments whose
  cells would share a trial id (including by case alone) are refused.
- `status` marks reports older than the log, and lists workspaces left behind; resume removes
  those. `docs/results/manipulation.py` counts what the report counts, which changes no
  published figure.
- Default `workspace_root`: when the system temp directory is inside the home directory (as
  on Windows), workspaces go to `agent-ab-workspaces` at the root of the home drive.

## 0.1.1 - 2026-10-30

### Added

- 40 example tasks (50 in total): 20 round-1 tasks, 10 bug hunts and 10 large features.
- `claude-code` options `capture_init` and `strict_mcp_config`, both on by default.
- Per trial: the models actually used, the CLI version and a scrubbed summary of the agent's
  init event (saved as `init.json`); reports show them per arm and flag differences.
- Per-trial record of how many trials were in flight at its start.
- Per trial: `prompt_sha256` (the exact prompt sent) and `instructions_sha256` (the workspace
  files `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md` and `AGENTS.md`, and adapter files
  such as the claude-code system-prompt file), next to the CLI version. Other files agents
  read from the workspace (`.claude/rules/`, skills, settings, `CLAUDE.md` in subdirectories,
  `AGENTS.override.md`) are not hashed.
- One-arm runs, for pilots that measure baseline difficulty.
- Manipulation check script, `docs/results/manipulation.py`.
- Example result: a re-run of the no-tests experiment with the current grader and Claude Code
  2.1.308 (`docs/results/haiku-5-5-no-tests-rerun`). Both of its arms also loaded the
  machine's user-level `CLAUDE.md`, so it is not a clean replication.

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
  Files outside the diff (interpreter caches such as a forged `.pyc`, the agent's `.git`) no
  longer reach the checks. A trial whose diff cannot be recorded or applied fails; a grading
  copy that cannot be set up or snapshotted is an infrastructure error. Setup now runs twice
  per trial; new artifacts `grade-setup.*`, `grade-workspace.txt`. Only what git records
  reaches the checks: empty directories do not, and on case-insensitive filesystems (Windows,
  macOS) a case-only rename is lost. A file git cannot read (for example unreadable on POSIX)
  fails the trial; before, such trials were graded in place.
- Diff recording tells its failures apart: a missing or replaced `.git` fails the trial as
  tampering, a git error fails it with git's message, and a `diff.patch` that cannot be written
  is an infrastructure error. Nested git repositories, whether the agent or the task's setup
  creates them, are recorded as plain files (in the setup baseline and in the agent's diff)
  instead of a gitlink that hides edits inside them, also when the agent staged them or added
  them with `git submodule add`. A stale `.git/index.lock` is removed before the diff, and the
  workspace's repository config is reset to agent-ab's copy, so a git filter the agent
  configured does not run inside agent-ab's own `git add`. `diff_stats` now raises (`GitDirAlteredError`, `WorkspaceError`, `OSError`)
  instead of returning None for these cases.
- `run_check` resolves a relative `report_path` before handing it to the check, which runs in
  the workspace.
- Argv checks of the form `{python} -m unittest ...` run under a verifying runner
  (`agent_ab.checkrun`) that records the outcome out of band with a one-time nonce
  (`check-report.json`). Agent code that forces the exit status (an `atexit` hook calling
  `os._exit(0)`, `SkipTest` at import, `sys.exit(0)` at import of a test module named on the
  command line) no longer fakes a pass; with discovery, unittest already reported
  `sys.exit(0)` at import as an error. Skipped
  hidden tests and runs with no tests now count as failures.
- `feature-uri-resolve`: the hidden oracle and the reference solution lowercased percent-encoding
  hex digits in a host, contradicting the prompt (and RFC 3986 section 6.2.2.1). They now keep
  them uppercase, and the check has an explicit case. Earlier results predate the fix; the
  no-tests re-run uses it.
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
