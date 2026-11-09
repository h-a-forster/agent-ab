# Backlog

## In progress

## Waiting on me

- v0.1.1 tagged at `db3cb78` (the last commit before trial isolation) with a GitHub release from `docs/release-notes-0.1.1.md`; its dated CHANGELOG entry and release notes say 2026-10-30, so update them if it is tagged later.
- Remote branches `claude/audit-fixes-2026-10-10`, `claude/hygiene-2026-10-15` and `upgrades-2026-10-23` deleted (merged or superseded by `main`).

## Decided

## Proposed

- A grader change that keeps `__version__` is noticed on resume (`0.1.1` covers both the audited and the fixed grader, and installs are from GitHub): bump the version when this branch merges, which is a release decision; a recorded grader revision only moves the same manual step, and hashing the source would refuse resumes after unrelated edits.
- `agent-ab report` survives absurd costs on planned records in old logs (1e308 crashes the bootstrap and totals, as it did before the audit fixes): every cost reader needs the sanitised value, so it is more than a small fix, and only logs from before `_sane_cost` can hold them.
- `validate` warns when an isolated agent's `python` is missing from `PATH` or is a different major version from the interpreter checks use (the divergence itself is documented in `docs/adapters.md`).
- `README.md` findings lead with a clean run, or group the two confounded numbers under one "both runs confounded" header, so `-2.7 pts` is not read before the caveat.
- The offline suite costs less CI time (5 minutes per matrix cell, mostly `tests/test_proc.py`).
- The no-tests experiment re-run with isolation on, so the repository has one clean replication of its headline.
- The leak check made complete: an `InstructionsLoaded` hook passed with `--settings` lists every memory file loaded (seen working on Claude Code 2.1.308 without a credential), and could replace reading the init event.
- `codex` trials isolated from user-level configuration the way `claude-code` trials are.
- The notes in `docs/release-notes-0.2.0.md` folded into `CHANGELOG.md` when that version is released.
- The pilots and the Haiku-vs-Sonnet comparison re-run under the clean-copy grader, if they are still cited.
- Research questions under "Open questions" in `README.md` answered: per-task no-tests losses, task headroom for Haiku 5.5, heterogeneous effects in the power model, concurrency and time ratios, environment-provided skills.
