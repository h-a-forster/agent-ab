"""Manipulation check for the no-tests experiments: did each trial write or run tests?

Usage: python docs/results/manipulation.py RUN_DIR [--out FILE.jsonl]

Reads the per-trial artifacts of a run made with the claude-code adapter and
``capture_init`` on (stream-json transcripts):

- wrote_tests: the trial's diff.patch adds or changes a file named ``test_*.py`` or
  ``*_test.py``, or a file under a ``tests/`` directory.
- ran_tests: a Bash tool call invoked unittest or pytest, or ran a ``test_*.py`` file with
  Python. Reading a test file (``cat tests/test_x.py``) does not count.

Prints a per-arm summary; with --out, writes one JSON line per final trial attempt (small
enough to commit, unlike the artifacts). Heuristic: a trial that tests through some other
route (say, an ad hoc ``python -c`` script) counts as not running tests.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$)")
_RUNS_TESTS = re.compile(
    r"-m\s+(unittest|pytest)\b|(^|[\s;&|(])pytest\b|python[0-9.]*\s+(\S*/)?test_\w*\.py"
)


def wrote_tests(diff: str) -> bool:
    paths = re.findall(r"^\+\+\+ b/(.+)$", diff, flags=re.MULTILINE)
    return any(_TEST_FILE.search(p) for p in paths)


def bash_commands(transcript: str) -> list[str]:
    commands = []
    for line in transcript.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []) or []:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") == "Bash"
            ):
                commands.append(str(block.get("input", {}).get("command", "")))
    return commands


def check_trial(art: Path) -> dict:
    patch, stdout = art / "diff.patch", art / "agent.stdout"
    diff = patch.read_text("utf-8", "replace") if patch.exists() else ""
    transcript = stdout.read_text("utf-8", "replace") if stdout.exists() else ""
    commands = bash_commands(transcript)
    return {
        "wrote_tests": wrote_tests(diff),
        "ran_tests": any(_RUNS_TESTS.search(c) for c in commands),
        "bash_calls": len(commands),
    }


def final_records(run_dir: Path) -> list[dict]:
    final: dict[str, dict] = {}
    for line in (run_dir / "trials.jsonl").read_text("utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            final[rec["trial_id"]] = rec  # later attempts replace earlier ones
    return [final[k] for k in sorted(final)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_dir", type=Path)
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    rows = []
    for rec in final_records(args.run_dir):
        art = args.run_dir / rec["artifacts"]
        if not art.is_dir():
            print(f"missing artifacts for {rec['trial_id']}", file=sys.stderr)
            return 1
        rows.append({"trial_id": rec["trial_id"], "task": rec["task"], "arm": rec["arm"],
                     "passed": rec["passed"], **check_trial(art)})  # fmt: skip

    by_arm: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)
    for arm, items in sorted(by_arm.items()):
        n = len(items)
        wrote = sum(r["wrote_tests"] for r in items)
        ran = sum(r["ran_tests"] for r in items)
        print(f"{arm}: wrote tests in {wrote}/{n} trials, ran tests in {ran}/{n}")
    if args.out:
        args.out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
