"""``agent-ab init``: write a small, runnable offline demo experiment.

The demo uses the built-in ``mock`` adapter, so it runs in seconds with no network, API keys
or cost, and exercises the whole pipeline: workspaces, overlays, hidden checks, statistics
and reports. A commented Claude Code template sits next to it as the starting point for a
real experiment. Templates are plain string data so they ship inside the package.
"""

from __future__ import annotations

from pathlib import Path

from agent_ab.errors import AgentABError

CHECK_ARGV = '["{python}", "-m", "unittest", "discover", "-s", "checks", "-t", "."]'


class ScaffoldError(AgentABError):
    """The target directory cannot receive the demo files."""


# --------------------------------------------------------------------------- experiment files

_EXPERIMENT = """\
# agent-ab demo experiment.
#
# Runs offline with the built-in "mock" adapter: a fake agent that "solves" a task by
# copying the task's solution/ into the workspace with a set probability. No network,
# no API keys, no cost. Use it to see the whole pipeline before pointing agent-ab at a
# real agent (see experiment.claude-code.toml).
#
#   agent-ab validate experiment.toml --tasks   # each check must fail before, pass after
#   agent-ab run experiment.toml                # 4 tasks x 2 arms x 2 repeats = 16 trials

name = "demo"
description = "Does an instruction file help? (simulated with the mock adapter)"
tasks = ["tasks/*"]      # every directory under tasks/ that holds a task.toml
repeats = 2              # agents are not deterministic: run each task/arm pair twice
jobs = 4                 # concurrent trials
seed = 73                # fixes the trial order and every trial's seed (and so the result)
timeout_s = 60           # agent wall-clock limit per attempt
check_timeout_s = 60     # hidden check limit
baseline = "control"     # every other arm is compared against this one

[agent]                  # defaults shared by every arm
adapter = "mock"

[agent.options]          # adapter-specific settings (see docs/adapters.md)
solve_rate = 0.5         # chance of solving a task that task_rates does not list
cost_usd = [0.02, 0.03]  # simulated spend per trial, uniform in [low, high]
duration_s = [0.0, 0.2]  # simulated thinking time, kept tiny for the demo
tokens = 1500

[[arms]]
name = "control"
description = "Stock setup"
[arms.agent.options.task_rates]   # per-task solve chance, merged over [agent.options]
fix-slugify = 0.7
roman-numerals = 0.5
merge-intervals = 0.3
parse-duration = 0.2

[[arms]]
name = "with-guide"
description = "Adds an AGENTS.md with working rules"
overlay = "arms/with-guide"   # copied into the workspace before the agent starts
[arms.agent.options]     # the simulated guide helps on every task but costs a little more
cost_usd = [0.03, 0.04]
[arms.agent.options.task_rates]
fix-slugify = 0.9
roman-numerals = 0.8
merge-intervals = 0.6
parse-duration = 0.5
"""

_EXPERIMENT_CLAUDE = """\
# agent-ab experiment template for Claude Code.
#
# WARNING: this launches real agents, unattended, with full permissions
# (permission_mode = "bypassPermissions"). The workspace is a temporary directory, NOT a
# sandbox: an agent can read and change anything this account can, and use the network.
# Run it inside a container or a disposable VM that holds only the credentials the agent
# needs, and keep a budget. See the project's docs/safety.md.
#
# It reuses the demo tasks. They are tiny, so expect both arms to solve almost all of them;
# replace tasks/ with tasks taken from your own codebase to learn something useful.
#
#   agent-ab validate experiment.claude-code.toml --tasks
#   agent-ab run experiment.claude-code.toml --dry-run
#   agent-ab run experiment.claude-code.toml

name = "claude-code-guide"
description = "Does an AGENTS.md with working rules change the pass rate?"
tasks = ["tasks/*"]
repeats = 3
jobs = 2
seed = 0
budget_usd = 5.0         # stop starting new trials once recorded spend reaches this
timeout_s = 900          # agent wall-clock limit per attempt
check_timeout_s = 120
max_retries = 2          # extra attempts after infrastructure errors (auth, rate limits)
baseline = "control"

[agent]
adapter = "claude-code"
model = "sonnet"
effort = "medium"        # low | medium | high | xhigh | max

[agent.options]
permission_mode = "bypassPermissions"   # nobody is there to approve tool calls
setting_sources = "project"   # only workspace settings, so local configuration cannot leak in
max_turns = 30
max_budget_usd = 0.50    # per-trial spend cap enforced by the claude CLI

[[arms]]
name = "control"
description = "No instruction file"

[[arms]]
name = "with-guide"
description = "AGENTS.md with working rules (CLAUDE.md imports it)"
overlay = "arms/with-guide"

# More things worth comparing, one change per arm:
#
# [[arms]]
# name = "opus"
# [arms.agent]
# model = "opus"
#
# [[arms]]
# name = "high-effort"
# [arms.agent]
# effort = "high"
#
# [[arms]]
# name = "tests-first"
# prompt_suffix = "Before changing code, write a failing test that reproduces the problem."
"""

_GUIDE = """\
# Working rules

- Read the relevant code and any existing tests before changing anything.
- Make the smallest change that fixes the problem; keep the public interface unchanged.
- Handle edge cases explicitly: empty input, boundaries, invalid values.
- Run the code on a few examples before you finish.
"""

# Claude Code reads CLAUDE.md, not AGENTS.md; an import keeps a single source of rules.
_GUIDE_CLAUDE = "@AGENTS.md\n"

_GITIGNORE = """\
runs/
__pycache__/
*.pyc
"""

_README = """\
# agent-ab demo

A small, offline A/B experiment. It asks: does adding an `AGENTS.md` with working rules
change how often an agent solves a task? The agent here is the built-in `mock` adapter,
which "solves" a task by copying its reference solution with a fixed probability, so the
whole run takes seconds and costs nothing. The numbers are simulated; the pipeline is real.

## Layout

```text
experiment.toml               the demo experiment (mock adapter, 2 arms, 2 repeats)
experiment.claude-code.toml   commented template for a real Claude Code experiment
arms/with-guide/              files copied into the workspace for the "with-guide" arm
tasks/<task>/
  task.toml                   prompt and hidden check command
  repo/                       starting files the agent sees
  checks/                     hidden files, copied over the workspace after the agent finishes
  solution/                   reference fix (used by validate --tasks and the mock agent)
runs/                         one directory per run (ignored by git)
```

## Try it

```sh
agent-ab validate experiment.toml --tasks   # every check fails before and passes after
agent-ab run experiment.toml --dry-run      # what would run
agent-ab run experiment.toml                # run it; prints a report
agent-ab status runs/<run-dir>              # progress, spend, errors
agent-ab report runs/<run-dir> --format html --out report.html
```

The simulated guide solves 25 points more often, yet the verdict is "no detectable
difference": with only 4 tasks no result can reach p < 0.05, as the report's notes explain.
The cost difference, measured on every trial, is detected. Add tasks, raise `repeats`, or
change `task_rates` and `seed` in `experiment.toml` to see how the verdicts move.

## Next: a real agent

`experiment.claude-code.toml` runs the same comparison with Claude Code. Read the warning
at its top first: real agents run unattended with full permissions, so use a container or
a disposable VM, and set a budget. Then replace `tasks/` with tasks from your own code.
"""


# --------------------------------------------------------------------------- tasks


def _task_toml(prompt: str) -> str:
    return f'prompt = """\n{prompt}"""\ncheck = {CHECK_ARGV}\ncheck_timeout_s = 60\n'


_TASKS: dict[str, dict[str, str]] = {
    "fix-slugify": {
        "task.toml": _task_toml(
            "`slugify(text)` in text_utils.py should lowercase the text, replace each run of\n"
            "characters that are not letters or digits with a single hyphen, and strip leading\n"
            "and trailing hyphens. It currently keeps punctuation. Fix it.\n"
        ),
        "repo/text_utils.py": '''\
"""Small text helpers."""


def slugify(text: str) -> str:
    """Turn ``text`` into a URL slug: lowercase words joined by single hyphens."""
    return text.lower().replace(" ", "-")
''',
        "solution/text_utils.py": '''\
"""Small text helpers."""

import re


def slugify(text: str) -> str:
    """Turn ``text`` into a URL slug: lowercase words joined by single hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
''',
        "checks/checks/test_slugify.py": """\
import unittest

from text_utils import slugify


class TestSlugify(unittest.TestCase):
    def test_punctuation(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_runs_collapse(self):
        self.assertEqual(slugify("a  --  b"), "a-b")

    def test_edges(self):
        self.assertEqual(slugify("--Already--"), "already")

    def test_plain(self):
        self.assertEqual(slugify("Plain words"), "plain-words")
""",
    },
    "roman-numerals": {
        "task.toml": _task_toml(
            "`to_roman(n)` in roman.py should convert an integer from 1 to 3999 to a Roman\n"
            "numeral using subtractive notation (4 is IV, 90 is XC, 1994 is MCMXCIV), and raise\n"
            "ValueError for numbers outside that range. Fix it.\n"
        ),
        "repo/roman.py": '''\
"""Roman numerals."""

_VALUES = [(1000, "M"), (500, "D"), (100, "C"), (50, "L"), (10, "X"), (5, "V"), (1, "I")]


def to_roman(n: int) -> str:
    """Convert ``n`` to a Roman numeral."""
    out = []
    for value, symbol in _VALUES:
        count, n = divmod(n, value)
        out.append(symbol * count)
    return "".join(out)
''',
        "solution/roman.py": '''\
"""Roman numerals."""

_VALUES = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def to_roman(n: int) -> str:
    """Convert ``n`` (1..3999) to a Roman numeral."""
    if not 1 <= n <= 3999:
        raise ValueError(f"out of range: {n}")
    out = []
    for value, symbol in _VALUES:
        count, n = divmod(n, value)
        out.append(symbol * count)
    return "".join(out)
''',
        "checks/checks/test_roman.py": """\
import unittest

from roman import to_roman


class TestRoman(unittest.TestCase):
    def test_additive(self):
        self.assertEqual(to_roman(3), "III")
        self.assertEqual(to_roman(2023), "MMXXIII")

    def test_subtractive(self):
        self.assertEqual(to_roman(4), "IV")
        self.assertEqual(to_roman(90), "XC")
        self.assertEqual(to_roman(1994), "MCMXCIV")

    def test_range(self):
        for bad in (0, -1, 4000):
            with self.assertRaises(ValueError):
                to_roman(bad)
""",
    },
    "merge-intervals": {
        "task.toml": _task_toml(
            "`merge(intervals)` in intervals.py should merge overlapping or touching closed\n"
            "intervals given as (start, end) tuples in any order, and return them sorted by\n"
            "start. It gets unsorted input and touching intervals wrong. Fix it.\n"
        ),
        "repo/intervals.py": '''\
"""Interval arithmetic."""


def merge(intervals):
    """Merge overlapping (start, end) intervals."""
    result = []
    for start, end in intervals:
        if result and start < result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result
''',
        "solution/intervals.py": '''\
"""Interval arithmetic."""


def merge(intervals):
    """Merge overlapping or touching (start, end) intervals; result sorted by start."""
    result = []
    for start, end in sorted(intervals):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], end))
        else:
            result.append((start, end))
    return result
''',
        "checks/checks/test_intervals.py": """\
import unittest

from intervals import merge


class TestMerge(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(merge([(1, 3), (2, 6), (8, 10)]), [(1, 6), (8, 10)])

    def test_unsorted(self):
        self.assertEqual(merge([(8, 10), (1, 3), (2, 6)]), [(1, 6), (8, 10)])

    def test_touching(self):
        self.assertEqual(merge([(1, 2), (2, 3)]), [(1, 3)])

    def test_empty(self):
        self.assertEqual(merge([]), [])
""",
    },
    "parse-duration": {
        "task.toml": _task_toml(
            '`parse_duration(text)` in durations.py should turn strings such as "90s", "15m"\n'
            'and "1h30m15s" into a number of seconds, and raise ValueError for empty or\n'
            'malformed input such as "", "5x" or "h1". It only handles a single unit. Fix it.\n'
        ),
        "repo/durations.py": '''\
"""Parse human-written durations."""

_UNITS = {"h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> int:
    """Return the number of seconds in a duration such as "1h30m"."""
    text = text.strip()
    unit = text[-1:]
    if unit not in _UNITS:
        raise ValueError(f"bad duration: {text!r}")
    return int(text[:-1]) * _UNITS[unit]
''',
        "solution/durations.py": '''\
"""Parse human-written durations."""

import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_PART = re.compile(r"(\\d+)([hms])")


def parse_duration(text: str) -> int:
    """Return the number of seconds in a duration such as "1h30m"."""
    text = text.strip()
    if not text or not re.fullmatch(r"(?:\\d+[hms])+", text):
        raise ValueError(f"bad duration: {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in _PART.findall(text))
''',
        "checks/checks/test_durations.py": """\
import unittest

from durations import parse_duration


class TestParseDuration(unittest.TestCase):
    def test_single_unit(self):
        self.assertEqual(parse_duration("90s"), 90)
        self.assertEqual(parse_duration("15m"), 900)

    def test_combined(self):
        self.assertEqual(parse_duration("1h30m15s"), 5415)
        self.assertEqual(parse_duration("2h5s"), 7205)

    def test_invalid(self):
        for bad in ("", "5x", "h1", "1h 30m"):
            with self.assertRaises(ValueError):
                parse_duration(bad)
""",
    },
}


def scaffold_files() -> dict[str, str]:
    """Every demo file as {posix relative path: text}."""
    files = {
        "experiment.toml": _EXPERIMENT,
        "experiment.claude-code.toml": _EXPERIMENT_CLAUDE,
        "arms/with-guide/AGENTS.md": _GUIDE,
        "arms/with-guide/CLAUDE.md": _GUIDE_CLAUDE,
        ".gitignore": _GITIGNORE,
        "README.md": _README,
    }
    for task_id, task_files in _TASKS.items():
        # checks/ is copied over the workspace root, so the hidden tests live in checks/checks/;
        # its empty __init__.py lets `unittest discover -s checks -t .` import them.
        files[f"tasks/{task_id}/checks/checks/__init__.py"] = ""
        for rel, text in task_files.items():
            files[f"tasks/{task_id}/{rel}"] = text
    return files


def init_project(dest: Path, *, force: bool = False) -> list[Path]:
    """Write the demo into ``dest`` and return the files written.

    Refuses a non-empty directory unless ``force``; even then only the demo's own files are
    (over)written and nothing else is touched or deleted.
    """
    dest = Path(dest)
    if dest.exists() and not dest.is_dir():
        raise ScaffoldError(f"{dest} exists and is not a directory")
    if dest.is_dir() and any(dest.iterdir()) and not force:
        raise ScaffoldError(
            f"{dest} is not empty; choose an empty directory or pass --force "
            "(existing demo files are overwritten, nothing is deleted)"
        )
    files = scaffold_files()
    for rel in files:
        target = dest.joinpath(*rel.split("/"))
        if target.is_dir():
            raise ScaffoldError(f"{target} is a directory; cannot write a file there")
    written: list[Path] = []
    try:
        for rel, text in files.items():
            target = dest.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
            written.append(target)
    except OSError as e:
        raise ScaffoldError(f"cannot write the demo into {dest}: {e}") from e
    return written
