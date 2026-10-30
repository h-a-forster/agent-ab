# agent-ab 0.1.1

Released 2026-10-30. Full list: [CHANGELOG.md](../CHANGELOG.md#011---2026-10-30).

## Grading

- Grading runs in a clean copy of the pristine task with only the agent's recorded diff
  applied, so files outside the diff (a forged `.pyc`, the agent's `.git`) no longer reach
  the hidden checks.
- `{python} -m unittest` checks run under a verifying runner that records the outcome out of
  band; agent code that forces the exit status no longer fakes a pass. Skipped hidden tests
  and runs with no tests count as failures.
- Checks run with `PYTHONSAFEPATH=1`, and diff recording tells tampering, git errors and
  infrastructure errors apart.

## Records and reports

- Each trial records the models used, the CLI version, a scrubbed summary of the agent's init
  event, its concurrency and hashes of the prompt and instruction files. Reports show them per
  arm and flag differences.
- `run.json` stores paths relative to the run directory. The fingerprint scheme changed:
  resume runs started with 0.1.0 with `--force`.
- Trials are shuffled by (task, repeat) block with the arms of a block adjacent.
- One-arm runs for pilots; `power` handles negative effects and missing headroom.

## Example tasks and results

- 40 new example tasks (50 in total), including 10 bug hunts and 10 large features.
- New example results: task-calibration pilots, a 50-task x 3-repeat no-tests experiment and
  a Haiku 5.5 vs Sonnet 5.5 comparison ([docs/results.md](results.md)).
- `feature-uri-resolve`: the hidden oracle and reference solution now follow the prompt.

The no-tests experiment was re-run with the clean-copy grader, the `feature-uri-resolve` fix
and Claude Code 2.1.308, and its headline replicated: -2.7 pts [-6.7, +1.3], against
-2.7 pts [-7.3, +1.3] in the original run. The pilots and the model comparison predate the
new grader and have not been re-graded.

## Install

```sh
uv tool install git+https://github.com/h-a-forster/agent-ab@v0.1.1
```
