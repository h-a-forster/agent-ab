# Examples

| Path | What it is |
|------|------------|
| [`quickstart/`](quickstart/experiment.toml) | Offline demo with the `mock` adapter: three arms, no API key, no cost. Start here. |
| [`claude-code/`](claude-code/experiment.toml) | Real template: does telling Claude Code not to write tests change pass rate and cost? |
| [`codex/`](codex/experiment.toml) | Real template: Codex reasoning effort `low` vs `high`. |
| [`tasks/`](tasks/) | Ten small Python tasks shared by all three experiments. |

```console
agent-ab validate examples/quickstart/experiment.toml --tasks   # every task fails before, passes after
agent-ab run examples/quickstart/experiment.toml
```

The real templates run autonomous agents with broad permissions on your machine and cost
money. Read the comments at the top of each file before running them, and prefer a container
or VM.

## The task suite

All tasks are pure Python (standard library only, Python 3.11+) and deterministic: no network,
no dependence on the current time or the host OS.

| Task | Kind | Difficulty |
|------|------|------------|
| `pagination-off-by-one` | bugfix | easy |
| `cli-min-level-flag` | feature | easy |
| `money-decimal-rounding` | bugfix | easy |
| `csv-quoted-newlines` | bugfix | medium |
| `config-validation-errors` | feature | medium |
| `semver-precedence` | feature | medium |
| `dedupe-quadratic` | perf | medium |
| `portable-path-normalize` | bugfix | medium |
| `dst-daily-schedule` | bugfix | hard |
| `lru-cache-thread-safety` | bugfix | hard |

## Task folder format

```text
tasks/<task-id>/
  task.toml         prompt, check command, optional limits and tags
  repo/             starting files copied into a fresh workspace (README, package, visible tests)
  checks/           hidden files copied over the workspace root after the agent finishes
    checks/         ...here a test package, so it lands at <workspace>/checks/
      __init__.py
      test_*.py
  solution/         reference fix, copied over the workspace by `validate --tasks` and the mock agent
```

The task id is the directory name. A minimal `task.toml`:

```toml
prompt = """
Describe the problem like an issue report: what is wrong, what the correct behaviour is,
and every edge case the hidden check will test.
"""
check = ["{python}", "-m", "unittest", "discover", "-s", "checks", "-t", "."]
check_timeout_s = 120          # optional
tags = ["bugfix", "easy"]      # optional
```

`check` runs in the workspace root; exit code 0 means the trial passed. `{python}` expands to
the interpreter running agent-ab and `{workspace}` to the workspace path. Use an argv list
rather than a shell string so the same check runs on Windows, macOS and Linux. Instead of
`prompt` you can point `prompt_file` at a Markdown file next to `task.toml`.

The contents of `checks/` and `solution/` are overlaid onto the workspace root, so their
paths mirror the workspace: `solution/pagekit/core.py` replaces `pagekit/core.py`, and
`checks/checks/test_x.py` becomes `checks/test_x.py`. Hidden files overwrite anything the
agent wrote at the same path.

## Writing good tasks

- The prompt states the required behaviour precisely; the hidden check tests exactly that,
  including the edge cases the prompt names, and nothing the prompt does not ask for.
- Visible tests in `repo/tests/` pass on the starting code, so the agent can run them.
- The hidden check fails on the untouched repo and passes with `solution/` applied; verify with
  `agent-ab validate <experiment> --tasks`, and run it a few times to catch flaky checks.
- Time limits in checks should be generous (an order of magnitude above a good solution) and
  enforced inside the check, so slow code fails quickly instead of hanging until the timeout.
