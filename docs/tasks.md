# Tasks

A task is a prompt, starting files and a hidden pass/fail check. An experiment is only as
good as its tasks: a flaky or leaky check adds noise that statistics cannot remove.

## Layout

```text
tasks/fix-slugify/
  task.toml      required
  PROMPT.md      optional, if task.toml uses prompt_file
  repo/          starting files; the workspace is empty if absent
  checks/        hidden overlay, copied onto the workspace root after the agent finishes
  solution/      reference fix, an overlay used by validate --tasks and the mock adapter
```

The task id is the directory name. It must match `^[A-Za-z0-9][A-Za-z0-9._-]*$` and be
unique in the experiment.

- `repo/` is copied into a fresh workspace, dotfiles included. Any `.git` entry is skipped.
- `checks/` and `solution/` are **overlays**: their contents are copied onto the workspace
  root, overwriting files at the same paths. So `checks/grade.py` lands at
  `<workspace>/grade.py`, and `checks/checks/test_x.py` lands at
  `<workspace>/checks/test_x.py`. The checks overlay is applied after the agent finishes,
  so the agent never sees those files in its workspace.
- `solution/` is never shown to a real agent.

## `task.toml`

| Key | Type | Default | Meaning |
|---|---|---|---|
| `prompt` | string | | Task description sent to the agent. |
| `prompt_file` | string | | File in the task directory holding the prompt. Set exactly one of `prompt` and `prompt_file`. |
| `check` | list or string | required | Hidden check. Runs in the workspace after the checks overlay. Exit code 0 is a pass. |
| `setup` | list or string | none | Runs in the workspace before the agent. Failure or timeout is an infrastructure error. |
| `timeout_s` | number | experiment value | Agent time limit for this task. |
| `check_timeout_s` | number | experiment value | Check time limit. A timeout is a fail. |
| `tags` | list of strings | `[]` | Labels for your own use. |

A list runs directly as argv. A string runs through the shell (`cmd.exe` on Windows,
`/bin/sh` elsewhere). Prefer lists.

Placeholders: `{python}` is the interpreter running agent-ab; `{workspace}` is the workspace
path. Write literal braces as `{{` and `}}`.

## Validate: fail before, pass after

```sh
agent-ab validate experiment.toml --tasks
```

For each task this runs the check twice, with the checks overlay applied:

1. On the untouched `repo/`. The check must fail; otherwise the task measures nothing.
2. On `repo/` plus `solution/`. The check must pass; otherwise the check is wrong or the
   task is impossible.

It exits with code 1 if any task fails either step. Run it after every task change and on
every platform you use. Write a `solution/` for every task.

## Hidden checks

- Put grading tests in `checks/`, not `repo/`. The agent can read and edit anything in
  `repo/`.
- Put everything the check imports (fixtures, `conftest.py`, data files) in `checks/` too.
  The overlay overwrites whatever the agent wrote at those paths.
- Test the behaviour the prompt describes, not a particular implementation.
- State in the prompt what will be checked: the function, its signature, the edge cases.
- Visible tests in `repo/` are fine; the hidden check should cover more.
- The files are hidden from the workspace, not from the machine. An agent with full
  permissions can read the task directory. See [safety.md](safety.md).

## Flaky and slow checks

agent-ab lists tasks whose outcome varied across repeats within an arm as flaky. Some of that
is the agent; make sure none of it is the check.

- No dependence on wall-clock time, time zone, locale, unseeded randomness, or test order.
- No network. Vendor dependencies in `repo/` or `checks/`, or bake them into your image.
- Set `check_timeout_s` to a few times what the reference solution needs. Enforce tighter
  limits inside the tests so slow code fails fast.
- Close stdin or pass non-interactive flags to anything that might prompt.
- Run `agent-ab validate --tasks` several times.

## Cross-platform

- Use argv lists and `{python}` instead of shell strings and `python3`.
- Use `pathlib`; do not hard-code path separators.
- Normalise line endings before comparing text. The workspace is snapshotted with
  `core.autocrlf=false`, so files keep their bytes.

## Choosing tasks

- Many small tasks beat a few large ones. The task is the unit of replication; see
  [statistics.md](statistics.md#how-many-tasks).
- Tasks every arm always solves, or never solves, cannot show a difference. A baseline pass
  rate of roughly 30-70% is most informative.
- Freeze the suite before looking at results. Editing a task changes the fingerprint, so a
  resumed run will not mix versions.

## Example

```text
tasks/fix-slugify/
  task.toml
  repo/text_utils.py
  checks/checks/__init__.py               -> <workspace>/checks/__init__.py
  checks/checks/test_slugify_hidden.py    -> <workspace>/checks/test_slugify_hidden.py
  solution/text_utils.py                  -> <workspace>/text_utils.py
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

`unittest discover -s checks -t .` finds the tests in `<workspace>/checks/` and imports
`text_utils` from the workspace root.

`checks/checks/test_slugify_hidden.py`:

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

Validate it:

```sh
agent-ab validate experiment.toml --tasks --only fix-slugify
```

The tasks in [examples/tasks](../examples/tasks) follow this layout.
