# Backlog

## In progress

## Waiting on me

- Branch `polish-2026-10-30` merged into `main` through a pull request with CI green (CI has never run on this branch, including the SHA-pinned actions).
- v0.1.1 tagged at `8cd03a8` (the last commit before trial isolation) with a GitHub release from `docs/release-notes-0.1.1.md`; its dated CHANGELOG entry and release notes say 2026-10-30, so update them if it is tagged later.
- A one-trial real run with `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` shows that an isolated agent authenticates and runs Bash, with `config_leaks` empty and no user-level rules in the transcript.
- Decision on the 7 commits on `polish-2026-10-30` and 21 on `main` that carry a Claude `Co-Authored-By` trailer: reword the polish commits before merging, or leave them.
- Remote branches `claude/audit-fixes-2026-10-10`, `claude/hygiene-2026-10-15` and `upgrades-2026-10-23` deleted (merged or superseded by `main`).

## Decided

## Proposed

- `validate` warns when an isolated agent's `python` is missing from `PATH` or is a different major version from the interpreter checks use (the divergence itself is documented in `docs/adapters.md`).
- A run stops on repeated infrastructure errors of any kind in one arm (auth, rate limit), not only on isolation breaches.
- `README.md` findings lead with a clean run, or group the two confounded numbers under one "both runs confounded" header, so `-2.7 pts` is not read before the caveat.
- The offline suite costs less CI time (5 minutes per matrix cell, mostly `tests/test_proc.py`).
- The no-tests experiment re-run with isolation on, so the repository has one clean replication of its headline.
- The leak check made complete: an `InstructionsLoaded` hook passed with `--settings` lists every memory file loaded (seen working on Claude Code 2.1.308 without a credential), and could replace reading the init event.
- `codex` trials isolated from user-level configuration the way `claude-code` trials are.
- The notes in `docs/release-notes-0.2.0.md` folded into `CHANGELOG.md` when that version is released.
- Resuming a run started before isolation refuses instead of mixing unisolated and isolated trials (today it is only documented).
- The pilots and the Haiku-vs-Sonnet comparison re-run under the clean-copy grader, if they are still cited.
- Research questions under "Open questions" in `README.md` answered: per-task no-tests losses, task headroom for Haiku 5.5, heterogeneous effects in the power model, concurrency and time ratios, environment-provided skills.
