# Writing tasks

A task is one unit of work with a hidden pass/fail check. The quality of an experiment is
bounded by the quality of its tasks: a flaky or leaky check adds noise that no amount of
statistics can remove.

## Layout

```text
tasks/
  fix-slugify/
    task.toml      # required
    PROMPT.md      # optional, if task.toml uses prompt_file
    repo/          # optional starting files; empty workspace if absent
    checks/        # hidden files, copied in after the agent finishes
    solution/      # optional reference solution overlay
```

The task id is the directory name. It must match `^[A-Za-z0-9][A-Za-z0-9._-]*$` and be
unique within the experiment.

- `repo/` is copied into a fresh workspace, including dotfiles, excluding `.git`
  directories.
- `checks/` is copied over the workspace root **after** the agent finishes, overwriting files
  at the same paths. The agent never sees these files.
- `solution/` is copied over the workspace by `agent-ab validate --tasks` and by the `mock`
  adapter. It is never shown to a real agent.

## `task.toml`

```toml
prompt = """
slugify() in text_utils.py turns "Hello, World!" into "hello,-world!".
It should produce "hello-world". Fix it without changing its signature.
"""
check = ["{python}", "-m", "unittest", "discover", "-s", "checks", "-t", "."]
setup = ["{python}", "-m", "pip", "install", "-e", "."]
timeout_s = 900
check_timeout_s = 120
tags = ["bugfix", "python"]
```

| Key | Type | Default | Meaning |
|---|---|---|---|
| `prompt` | string | one of `prompt`/`prompt_file` required | The task description given to the agent. |
| `prompt_file` | string | | File, relative to the task directory, holding the prompt. |
| `check` | list of strings or string | required | Hidden check. Exit code 0 = pass. Runs in the workspace after `checks/` is copied in. |
| `setup` | list of strings or string | none | Runs in the workspace before the agent. A non-zero exit or timeout is an infrastructure error. |
| `timeout_s` | float | experiment `timeout_s` | Agent wall-clock limit for this task. |
| `check_timeout_s` | float | experiment `check_timeout_s` | Check limit for this task. A check timeout is a fail. |
| `tags` | list of strings | `[]` | Labels for your own bookkeeping. |

Exactly one of `prompt` and `prompt_file` must be set. Unknown keys are errors.

A command given as a list is run directly (argv). A command given as a string is run
through the shell (`cmd.exe` on Windows, `/bin/sh` elsewhere). Prefer lists.

Placeholders: `{python}` expands to the interpreter running agent-ab, `{workspace}` to the
workspace path. Write literal braces as `{{` and `}}`.

## Validate every task: fail before, pass after

```sh
agent-ab validate experiment.toml --tasks
```

For each task this:

1. runs the check against the untouched starting files with the hidden checks installed. The
   check **must fail**; otherwise the task is already solved and measures nothing.
2. if `solution/` exists, runs the check against the starting files plus the solution. The
   check **must pass**; otherwise the check is broken or the task is impossible.

It prints a table and exits with code 1 if any task has a problem. Run it after every change
to a task, and on every platform you plan to run experiments on.

Write a `solution/` for every task. It is the only cheap evidence that the task is solvable
and the check is correct.

## Hidden checks

- **Keep the grading tests in `checks/`, not in `repo/`.** Anything in `repo/` is visible to
  the agent, which can read it, overfit to it, or edit it.
- **Overwrite, don't trust.** Because `checks/` is copied last, an agent that edits a test
  file at the same path cannot change the grading. Any helper the check imports (fixtures,
  conftest files, data files) belongs in `checks/` too.
- **Check behaviour, not implementation.** Test the public interface the prompt describes.
  Checks that require a particular function name or file layout the prompt did not mention
  penalise valid solutions.
- **Say in the prompt what will be checked**, without giving the tests away: the function,
  its signature, the expected behaviour. A task that hinges on guessing an unstated
  requirement measures luck.
- **Hidden from the workspace, not from the machine.** The agent's workspace does not
  contain `checks/` or `solution/`, but an agent with full permissions could read the task
  directory if it went looking. See [safety.md](safety.md#what-isolation-you-get-and-what-you-dont).
- **It is fine for `repo/` to contain visible tests too.** Agents often run them. The hidden
  check should cover more cases than the visible ones.

## Avoid flaky checks

A check that sometimes fails on a correct solution adds noise to every arm and shrinks the
effects you can detect. agent-ab reports tasks whose outcome varied across repeats within an
arm as **flaky tasks**; investigate them.

- No dependence on wall-clock time, time zones, locale, random seeds you do not fix, or
  dictionary/set ordering across processes.
- No reliance on test execution order or on state left by an earlier test.
- No race conditions: avoid sleeps and polling; if you must wait, wait on a condition with a
  generous deadline.
- Run `agent-ab validate --tasks` several times. A check that changes outcome between runs on
  the same files is flaky.

## Time-bound checks

Agent solutions can hang: an infinite loop, a server that never exits, a prompt for input.

- Set `check_timeout_s` to a few times what the reference solution takes. A timed-out check
  is a fail, so do not set it so tight that a slow machine fails correct solutions.
- Give individual tests their own timeouts where your framework supports it.
- Close stdin for anything that might prompt, or pass explicit non-interactive flags.

## Network-free

Checks should not need the network. Network access makes checks slow and flaky, and makes
results depend on the state of external services.

- Vendor test dependencies in `repo/` or `checks/`, or install them in an image you run
  experiments in.
- If `setup` must install packages, prefer installing from local files. A failing `setup` is
  an infrastructure error: the attempt is retried and, if it keeps failing, excluded.

## Cross-platform commands

Experiments are often run on more than one operating system.

- Use argv lists, not shell strings: quoting, globbing and builtins differ between `cmd.exe`
  and `/bin/sh`.
- Use `{python}` instead of `python` or `python3`. It is the interpreter running agent-ab,
  so it exists on every platform and needs nothing on `PATH`.
- Do not hard-code path separators in checks; use `pathlib` or `os.path.join`.
- Write fixture files with explicit line endings, and compare text after normalising line
  endings. The workspace is snapshotted with `core.autocrlf=false`, so files keep the bytes
  you wrote.
- Prefer a Python check script over a shell script for anything beyond running a test
  runner:

```toml
check = ["{python}", "checks/grade.py"]
```

## Choosing tasks

- **Many small tasks beat a few large ones.** The task is the unit of replication; see
  [statistics.md](statistics.md#power-rule-of-thumb).
- **Aim for the middle.** Tasks every arm always solves, or never solves, cannot show a
  difference. A suite where the baseline passes roughly 30-70% of the time is most
  informative.
- **Match the change you are testing.** If you are testing a "write tests first"
  instruction, include tasks where testing plausibly helps and tasks where it plausibly
  doesn't.
- **Freeze the suite before you look at results.** Adding or dropping tasks after seeing
  which arm wins biases the comparison. Editing a task changes the experiment's fingerprint,
  so a resumed run will refuse to mix old and new versions.

## Example: a complete Python task

```text
tasks/fix-slugify/
  task.toml
  repo/text_utils.py
  checks/__init__.py            # empty; lets unittest import checks as a package
  checks/test_slugify_hidden.py
  solution/text_utils.py
```

`task.toml`:

```toml
prompt = """
`slugify(text)` in text_utils.py should lowercase the text, replace each run of
non-alphanumeric characters with a single hyphen, and strip leading and trailing
hyphens. It currently keeps punctuation. Fix it.
"""
check = ["{python}", "-m", "unittest", "discover", "-s", "checks", "-t", "."]
check_timeout_s = 60
```

`checks/test_slugify_hidden.py`:

```python
import unittest

from text_utils import slugify


class TestSlugify(unittest.TestCase):
    def test_punctuation(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_runs_collapse(self):
        self.assertEqual(slugify("a  --  b"), "a-b")

    def test_edges(self):
        self.assertEqual(slugify("--Already--"), "already")
```

Then:

```sh
agent-ab validate experiment.toml --tasks --only fix-slugify
```
