"""Verifying drop-in for ``python -m unittest``, used to run hidden checks.

agent-ab runs argv checks of the form ``{python} -m unittest ...`` through this module. The
checks import the agent's code, which shares the process and can force its exit status: an
``atexit`` hook that calls ``os._exit(0)``, or ``sys.exit(0)`` at import time. The exit status
alone therefore cannot be trusted.

Before any test code is imported, this module removes a report path and a one-time nonce from
the environment. After the run it writes the outcome, with the nonce, to that path. The grader
accepts a zero exit status only together with a report that carries the nonce and a clean
result, so cutting the process short or forcing its exit status no longer fakes a pass.

A clean result means at least one test ran and none failed, errored, succeeded unexpectedly or
was skipped. Skips count against the run because the agent's code can raise ``SkipTest``.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

REPORT_ENV = "AGENT_AB_CHECK_REPORT"
NONCE_ENV = "AGENT_AB_CHECK_NONCE"
REPORT_MAX_BYTES = 64 * 1024


def summarize(result: unittest.TestResult) -> dict[str, object]:
    """Counts from a finished run and whether they amount to a clean pass."""
    counts = {
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
    }
    ok = (
        counts["tests_run"] > 0
        and counts["failures"] == 0
        and counts["errors"] == 0
        and counts["skipped"] == 0
        and counts["unexpected_successes"] == 0
    )
    return {"ok": ok, **counts}


def _write_report(path: str, report: dict[str, object]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh)
        fh.write("\n")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    # Taken out of the environment before discovery imports anything from the workspace.
    report_path = os.environ.pop(REPORT_ENV, None)
    nonce = os.environ.pop(NONCE_ENV, None)
    args = sys.argv[1:] if argv is None else argv
    program = unittest.main(module=None, argv=["python -m unittest", *args], exit=False)
    summary = summarize(program.result)
    if summary["skipped"]:
        print("agent-ab: skipped tests count as failures in hidden checks", file=sys.stderr)
    if summary["tests_run"] == 0:
        print("agent-ab: no tests ran", file=sys.stderr)
    if report_path and nonce:
        _write_report(report_path, {"nonce": nonce, **summary})
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
