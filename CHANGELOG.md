# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.1.0 - 2026-10-09

Initial release.

### Added

- Experiment configuration in TOML: tasks, arms with agent defaults and per-arm overrides,
  prompt prefix/suffix, workspace overlays and removals, repeats, concurrency, timeouts,
  retries and a spend budget. Unknown keys are rejected with the key path.
- Task format: prompt, starting files, hidden checks copied in after the agent finishes,
  optional setup command and reference solution. `{python}` and `{workspace}` placeholders
  for cross-platform commands.
- Isolated temporary workspace per trial, snapshotted with git to record the agent's diff.
- Adapters: `claude-code`, `codex`, `command` (any agent, with a `usage.json` contract for
  cost and tokens) and `mock` (offline, deterministic).
- Infrastructure-error detection with retries; errored trials are excluded from statistics
  and reported.
- Run directory with `run.json`, append-only `trials.jsonl` and per-attempt artifacts;
  resume with a configuration fingerprint check.
- Statistics: task-level pass rates with cluster-bootstrap intervals, paired differences
  with bootstrap intervals, paired sign-flip permutation test, Holm correction, cost and
  time ratios, flaky-task detection, and conservative verdicts.
- Reports in text, Markdown, JSON and self-contained HTML.
- CLI commands: `init`, `validate` (including fail-before/pass-after task validation),
  `run`, `report`, `status`, `show`.
- Support for Linux, macOS and Windows on Python 3.11 to 3.13, with no runtime
  dependencies.
