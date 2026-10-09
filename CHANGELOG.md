# Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This
project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.1.0 - 2026-10-09

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
