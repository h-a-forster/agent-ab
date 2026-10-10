"""Command-line entry point: ``agent-ab init | validate | run | report | status | show | power``.

Output conventions: results go to stdout, progress and diagnostics to stderr. Streams keep
the console's encoding and replace what it cannot show; control characters from run data are
stripped before printing. Errors print ``agent-ab: error: <message>``; a traceback appears
only with ``AGENT_AB_DEBUG=1``.

Exit codes: 0 ok, 1 runtime failure or validation problems, 2 usage or configuration error,
130 interrupted.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import difflib
import json
import math
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
import traceback
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, TextIO

from agent_ab import __version__, power
from agent_ab.adapters import get_adapter
from agent_ab.config import compute_fingerprint, load_experiment
from agent_ab.errors import AgentABError, ConfigError, RunStoreError
from agent_ab.model import AgentSpec, Arm, Experiment, Task, TrialRecord, trial_id
from agent_ab.report import (
    fmt_cost,
    render_html,
    render_json,
    render_markdown,
    render_text,
)
from agent_ab.stats import analyze
from agent_ab.store import RUN_FILE, TRIALS_DIR, RunStore, is_done

PROG = "agent-ab"
EXIT_OK, EXIT_FAILURE, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130

_FORMAT_FILES = {
    "text": "report.txt",
    "md": "report.md",
    "json": "analysis.json",
    "html": "report.html",
}
_WAIT_S = 0.2  # main-thread wait slice; short so Ctrl-C is delivered promptly on Windows
_DISPLAY_CAP = 1e6  # larger costs and durations are shown as ">$1e6" / ">1e6s"

# Device names Windows reserves in every directory, with or without an extension.
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


class UsageError(AgentABError):
    """Bad command-line usage detected after parsing (exit code 2)."""


# --------------------------------------------------------------------------- output helpers


def _setup_streams() -> None:
    # Keep the console's encoding (a UTF-8 console must show non-ASCII paths intact so printed
    # commands can be copied), but replace what a legacy code page cannot encode: a replaced
    # character is better than a crash after an expensive run.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(errors="replace")


# ESC sequences (CSI, string commands such as OSC, two-byte escapes); then lone C0/C1 controls.
_ESCAPE_RE = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]?"
    r"|(?:\x1b[\]P^_X]|[\x90\x9d\x9e\x9f\x98])[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"
    r"|\x1b[ -/]*[0-~]?"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _clean(text: str) -> str:
    """Strip terminal escape sequences and control characters; tabs and newlines stay.

    Error messages, trial ids and file names come from run directories and agents, so they
    must not be able to move the cursor, retitle the window or hide earlier output.
    """
    return _CONTROL_RE.sub("", _ESCAPE_RE.sub("", text))


def _out(text: str = "") -> None:
    print(_clean(text), file=sys.stdout, flush=True)


def _err(text: str = "") -> None:
    print(_clean(text), file=sys.stderr, flush=True)


def _warn(text: str) -> None:
    _err(f"{PROG}: warning: {text}")


def _quote(arg: str) -> str:
    """Quote an argument for display in a copy-pasteable command line."""
    if arg and not any(c in arg for c in " \t\"'&|;<>()$`^%!*?[]{}"):
        return arg
    return '"' + arg.replace('"', '\\"') + '"'


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]], right: Sequence[int] = ()) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        widths = [max(w, len(c)) for w, c in zip(widths, row, strict=True)]

    def fmt(row: Sequence[str]) -> str:
        cells = [
            c.rjust(w) if i in right else c.ljust(w)
            for i, (c, w) in enumerate(zip(row, widths, strict=True))
        ]
        return "  ".join(cells).rstrip()

    lines = [fmt(headers), fmt(["-" * w for w in widths])]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


def _report_width() -> int:
    if not sys.stdout.isatty():
        return 100
    return max(80, min(140, shutil.get_terminal_size((100, 24)).columns))


def _short(text: str | None, limit: int = 100) -> str:
    one_line = " ".join((text or "").split())
    return one_line if len(one_line) <= limit else one_line[: limit - 3] + "..."


def _as_float(x: Any) -> float | None:
    """``x`` as a float: None if missing or not a number, +-inf if too large for a float."""
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        v = float(x)
    except OverflowError:  # an int beyond float range
        v = math.inf if x > 0 else -math.inf
    return None if math.isnan(v) else v


def _total(values: Iterable[Any]) -> float:
    """Sum that tolerates None, huge ints and infinities (records come from files on disk)."""
    total = 0.0
    for x in values:
        v = _as_float(x)
        if v is not None:
            total += v
    return 0.0 if math.isnan(total) else total


def _fmt_seconds(x: Any) -> str:
    v = _as_float(x)
    if v is None:
        return "-"
    if abs(v) >= _DISPLAY_CAP:
        return ">1e6s" if v > 0 else "<-1e6s"
    return f"{v:.1f}s"


def _fmt_cost(x: Any) -> str:
    v = _as_float(x)
    if v is None:
        return "-"
    if abs(v) >= _DISPLAY_CAP:
        return ">$1e6" if v > 0 else "<-$1e6"
    return fmt_cost(v)


# --------------------------------------------------------------------------- argument parsing


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text!r}")
    return value


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {text!r}") from None
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {text!r}")
    return value


def _alpha(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {text!r}") from None
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError(f"alpha must be between 0 and 1, got {text!r}")
    return value


def _name_list(text: str) -> list[str]:
    names = [n.strip() for n in text.split(",") if n.strip()]
    if not names:
        raise argparse.ArgumentTypeError("expected a comma-separated list of names")
    return names


def _add_selection(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--arms",
        type=_name_list,
        metavar="A,B",
        help="only these arms (comma-separated; the baseline must be included)",
    )
    p.add_argument(
        "--only",
        action="append",
        metavar="GLOB",
        help="only tasks whose id matches GLOB (repeatable)",
    )


def build_parser() -> argparse.ArgumentParser:
    """The argparse parser for every command."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Controlled A/B experiments for coding-agent setups.",
        epilog="Exit codes: 0 ok, 1 runtime failure or validation problems, "
        "2 usage or configuration error, 130 interrupted.",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser(
        "init",
        help="write a runnable offline demo experiment",
        description="Scaffold an offline demo (mock adapter, 4 tasks, 2 arms) "
        "and a commented Claude Code template.",
    )
    p.add_argument(
        "dir",
        nargs="?",
        default=".",
        metavar="DIR",
        help="target directory (default: current directory)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="write into a non-empty directory (demo files are overwritten, nothing is deleted)",
    )

    p = sub.add_parser(
        "validate",
        help="check a config and, with --tasks, every task",
        description="Load and check an experiment config. With --tasks, run each "
        "task's check on the untouched repo (must fail) and on "
        "repo + solution (must pass).",
    )
    p.add_argument("config", metavar="CONFIG", help="experiment TOML file")
    p.add_argument(
        "--tasks",
        action="store_true",
        help="verify each task's check fails before and passes after its solution",
    )
    p.add_argument(
        "--jobs",
        type=_positive_int,
        metavar="N",
        help="parallel task checks (default: the experiment's jobs)",
    )
    _add_selection(p)

    p = sub.add_parser(
        "run",
        help="run (or resume) an experiment",
        description="Run every planned trial, then print the text report and "
        "write report.html, report.md and analysis.json into the "
        "run directory.",
    )
    p.add_argument("config", metavar="CONFIG", help="experiment TOML file")
    where = p.add_mutually_exclusive_group()
    where.add_argument(
        "--out",
        metavar="DIR",
        help="run directory (default: runs/<name>-<UTC timestamp> next to CONFIG)",
    )
    where.add_argument("--resume", metavar="DIR", help="continue an existing run directory")
    p.add_argument("--jobs", type=_positive_int, metavar="N", help="concurrent trials")
    p.add_argument(
        "--repeats",
        type=_positive_int,
        metavar="N",
        help="repeats per task and arm (part of the fingerprint)",
    )
    p.add_argument(
        "--budget",
        type=_positive_float,
        metavar="USD",
        help="stop starting new trials once recorded spend reaches USD (must be > 0, "
        "like budget_usd in the config; omit for no budget)",
    )
    _add_selection(p)
    p.add_argument("--dry-run", action="store_true", help="plan only; create and run nothing")
    p.add_argument(
        "--keep-workspaces", action="store_true", help="keep each trial's workspace for inspection"
    )
    p.add_argument(
        "--force", action="store_true", help="resume even if the experiment fingerprint changed"
    )
    p.add_argument("--quiet", action="store_true", help="no per-trial progress lines")

    p = sub.add_parser(
        "report",
        help="analyse a run directory",
        description="Recompute the analysis of a run and render it.",
    )
    p.add_argument("run_dir", metavar="RUN_DIR")
    p.add_argument("--format", choices=sorted(_FORMAT_FILES), default="text")
    p.add_argument(
        "--out",
        metavar="FILE",
        help="write to FILE instead of stdout (a directory gets report.<ext>)",
    )
    p.add_argument("--baseline", metavar="ARM", help="compare against this arm")
    p.add_argument(
        "--alpha", type=_alpha, default=0.05, metavar="A", help="significance level (default 0.05)"
    )
    p.add_argument(
        "--seed",
        type=int,
        default=0,
        metavar="S",
        help="seed for bootstrap and permutation draws (default 0)",
    )

    p = sub.add_parser("status", help="progress, errors and spend of a run")
    p.add_argument("run_dir", metavar="RUN_DIR")

    p = sub.add_parser("show", help="one trial's record and artifact paths")
    p.add_argument("run_dir", metavar="RUN_DIR")
    p.add_argument("trial_id", metavar="TRIAL_ID", help="e.g. fix-slugify__control__r0")

    p = sub.add_parser(
        "power",
        help="how many tasks and repeats you need (simulation)",
        description="Estimate, by simulation, the chance that a run of a given size detects "
        "a given pass-rate improvement. Optionally base task difficulty on a pilot run.",
    )
    p.add_argument(
        "run_dir",
        metavar="RUN_DIR",
        nargs="?",
        help="pilot run whose baseline arm sets the task difficulty distribution",
    )
    p.add_argument(
        "--effect",
        default=power.DEFAULT_EFFECTS,
        metavar="PTS[,PTS...]",
        help=f"improvements to detect, in percentage points (default {power.DEFAULT_EFFECTS})",
    )
    p.add_argument(
        "--tasks",
        default=power.DEFAULT_TASKS,
        metavar="N[,N...]",
        help=f"task counts to simulate (default {power.DEFAULT_TASKS})",
    )
    p.add_argument(
        "--repeats",
        default=power.DEFAULT_REPEATS,
        metavar="R[,R...]",
        help=f"repeats per task and arm (default {power.DEFAULT_REPEATS})",
    )
    p.add_argument(
        "--alpha",
        default=power.DEFAULT_ALPHA,
        metavar="A",
        help=f"significance level (default {power.DEFAULT_ALPHA})",
    )
    p.add_argument(
        "--sims",
        default=power.DEFAULT_SIMS,
        metavar="N",
        help=f"simulated experiments per design (default {power.DEFAULT_SIMS})",
    )
    p.add_argument("--seed", default="0", metavar="S", help="simulation seed (default 0)")
    p.add_argument("--format", choices=("text", "md", "json"), default="text")
    return parser


# --------------------------------------------------------------------------- init


def cmd_init(args: argparse.Namespace) -> int:
    from agent_ab.scaffold import ScaffoldError, init_project

    dest = Path(args.dir)
    try:
        written = init_project(dest, force=args.force)
    except ScaffoldError as e:
        raise UsageError(str(e)) from None  # a wrong target directory is a usage error
    shown = args.dir if args.dir != "." else "the current directory"
    _out(f"Wrote an offline demo experiment to {shown} ({len(written)} files).")
    _out("")
    _out("Next steps:")
    if args.dir != ".":
        _out(f"  cd {_quote(args.dir)}")
    _out("  agent-ab validate experiment.toml --tasks   # checks fail before, pass after")
    _out("  agent-ab run experiment.toml                # 16 mock trials, under half a minute")
    _out("")
    _out("experiment.claude-code.toml is a template for a real agent; read its safety")
    _out("warning before running it.")
    return EXIT_OK


# --------------------------------------------------------------------------- validate


def _load(args: argparse.Namespace) -> Experiment:
    return load_experiment(args.config, select_arms=args.arms, select_tasks=args.only)


def _rel(path: Path | None, root: Path) -> str:
    if path is None:
        return "-"
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _availability(exp: Experiment) -> list[tuple[str, str | None]]:
    """(arm name, problem or None) for every arm's adapter."""
    out: list[tuple[str, str | None]] = []
    for arm in exp.arms:
        try:
            msg = get_adapter(arm.agent.adapter).check_available(arm.agent)
        except AgentABError as e:
            msg = str(e)
        except Exception as e:  # availability probes run external tools; never crash on them
            msg = f"availability check failed: {e}"
        out.append((arm.name, msg))
    return out


def _print_summary(exp: Experiment) -> None:
    _out(f"Experiment: {exp.name}")
    if exp.description:
        _out(f"  {_short(exp.description, 96)}")
    ids = [t.id for t in exp.tasks]
    shown = ", ".join(ids[:12]) + (f" and {len(ids) - 12} more" if len(ids) > 12 else "")
    _out(f"Tasks ({len(ids)}): {shown}")
    _out(f"Arms ({len(exp.arms)}, * = baseline):")
    rows = []
    for arm in exp.arms:
        a = arm.agent
        rows.append(
            [
                arm.name + (" *" if arm.name == exp.baseline else ""),
                a.adapter,
                a.model or "-",
                a.effort or "-",
                _rel(arm.overlay, exp.root),
                ",".join(arm.remove) or "-",
            ]
        )
    table = _table(["arm", "adapter", "model", "effort", "overlay", "remove"], rows)
    _out("\n".join("  " + line for line in table.splitlines()))
    planned = len(exp.tasks) * len(exp.arms) * exp.repeats
    _out(
        f"Planned trials: {len(exp.tasks)} tasks x {len(exp.arms)} arms x "
        f"{exp.repeats} repeats = {planned}"
    )
    _out(
        f"Jobs: {exp.jobs}   budget: {_budget_text(exp.budget_usd)}   "
        f"timeout: {exp.timeout_s:g}s   retries: {exp.max_retries}"
    )


def _budget_text(budget: float | None) -> str:
    return "none" if budget is None else _fmt_cost(budget)


@dataclasses.dataclass
class _TaskVerdict:
    task: str
    before: str = "-"
    after: str = "-"
    problems: list[str] = dataclasses.field(default_factory=list)


def _tail(path: Path, lines: int = 2) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    kept = [ln for ln in text.strip().splitlines() if ln.strip()][-lines:]
    return " | ".join(ln.strip() for ln in kept)


def _check_phase(
    exp: Experiment, task: Task, logs: Path, *, with_solution: bool, cancel: threading.Event
) -> tuple[str, str | None]:
    """Run setup (+ solution) + checks in a fresh workspace. Returns (outcome, problem)."""
    from agent_ab.workspace import (
        apply_solution,
        create_workspace,
        destroy_workspace,
        install_checks,
        run_check,
        run_command,
    )

    # A bare arm: tasks are validated on their own files, never with an arm's overlay.
    bare = Arm(name="validate", agent=AgentSpec(adapter="mock"))
    label = f"validate-{task.id}"
    phase = "after" if with_solution else "before"
    logs.mkdir(parents=True, exist_ok=True)
    ws = create_workspace(task, bare, root=exp.workspace_root, label=label)
    try:
        if task.setup is not None:
            timeout = task.timeout_s if task.timeout_s is not None else exp.timeout_s
            r = run_command(
                task.setup,
                ws,
                timeout_s=timeout,
                stdout_path=logs / f"{phase}-setup.stdout",
                stderr_path=logs / f"{phase}-setup.stderr",
                cancel=cancel,
            )
            if r.start_error or r.timed_out or r.exit_code != 0:
                why = r.start_error or ("timed out" if r.timed_out else f"exit {r.exit_code}")
                detail = _tail(logs / f"{phase}-setup.stderr")
                return "error", f"setup failed ({why})" + (f": {detail}" if detail else "")
        if with_solution:
            apply_solution(ws, task)
        install_checks(ws, task)
        timeout = task.check_timeout_s if task.check_timeout_s is not None else exp.check_timeout_s
        out, err = logs / f"{phase}-check.stdout", logs / f"{phase}-check.stderr"
        r = run_check(
            task.check, ws, timeout_s=timeout, stdout_path=out, stderr_path=err, cancel=cancel
        )
        if r.start_error:
            return "error", f"check could not start: {r.start_error}"
        if r.timed_out:
            return "timeout", f"check timed out after {timeout:g}s ({phase})"
        if r.exit_code is None:
            return "cancelled", "cancelled"
        outcome = "pass" if r.exit_code == 0 else "fail"
        if with_solution and outcome == "fail":
            detail = _tail(err) or _tail(out)
            return outcome, "check fails with the solution applied" + (
                f": {detail}" if detail else ""
            )
        if not with_solution and outcome == "pass":
            return outcome, "check passes on the untouched repo (the task is already solved)"
        return outcome, None
    finally:
        destroy_workspace(ws)


def _validate_task(
    exp: Experiment, task: Task, logs: Path, cancel: threading.Event
) -> _TaskVerdict:
    v = _TaskVerdict(task.id)
    try:
        v.before, problem = _check_phase(exp, task, logs, with_solution=False, cancel=cancel)
        if problem:
            v.problems.append(problem)
        if task.solution is None:
            v.after = "no solution"
        else:
            v.after, problem = _check_phase(exp, task, logs, with_solution=True, cancel=cancel)
            if problem:
                v.problems.append(problem)
    except AgentABError as e:
        v.problems.append(str(e))
    except Exception as e:  # one broken task must not hide the results of the others
        v.problems.append(f"unexpected {type(e).__name__}: {e}")
    return v


def _run_parallel(
    func: Callable[[Any], Any], items: Sequence[Any], jobs: int, cancel: threading.Event
) -> list[Any]:
    """Map ``func`` over ``items`` on a thread pool; Ctrl-C sets ``cancel`` and re-raises."""
    results: dict[int, Any] = {}
    pool = ThreadPoolExecutor(max_workers=max(1, jobs), thread_name_prefix="agent-ab-validate")
    futures: dict[Future, int] = {pool.submit(func, item): i for i, item in enumerate(items)}
    try:
        pending = set(futures)
        while pending:
            finished, pending = wait(pending, timeout=_WAIT_S, return_when=FIRST_COMPLETED)
            for fut in finished:
                results[futures[fut]] = fut.result()
    except BaseException:
        cancel.set()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return [results[i] for i in range(len(items))]


def cmd_validate(args: argparse.Namespace) -> int:
    exp = _load(args)
    _print_summary(exp)
    problems = 0

    _out("Adapters:")
    for arm_name, msg in _availability(exp):
        _out(f"  {arm_name}: " + ("available" if msg is None else f"NOT available: {msg}"))
        if msg is not None:
            _warn(f"arm {arm_name!r} cannot run on this machine: {msg}")
    if len(exp.arms) < 2:
        _warn("only one arm: 'run' needs at least two to compare")

    if args.tasks:
        jobs = args.jobs or exp.jobs
        _out("")
        _out(f"Checking {len(exp.tasks)} tasks (jobs={jobs}) ...")
        cancel = threading.Event()
        with tempfile.TemporaryDirectory(prefix="agent-ab-validate-") as tmp:

            def check(task: Task) -> _TaskVerdict:
                return _validate_task(exp, task, Path(tmp) / task.id, cancel)

            verdicts: list[_TaskVerdict] = _run_parallel(check, list(exp.tasks), jobs, cancel)
        rows = [
            [v.task, v.before, v.after, "ok" if not v.problems else "PROBLEM"] for v in verdicts
        ]
        _out(_table(["task", "before (must fail)", "after (must pass)", "result"], rows))
        bad = [v for v in verdicts if v.problems]
        no_solution = [v.task for v in verdicts if v.after == "no solution"]
        if bad:
            _out("")
            _out("Problems:")
            for v in bad:
                for p in v.problems:
                    _out(f"  {v.task}: {_short(p, 300)}")
        if no_solution:
            _warn(
                f"{len(no_solution)} task(s) have no solution/, so only the 'must fail' half "
                f"was checked: {', '.join(no_solution[:10])}"
            )
        problems += len(bad)
        _out("")
        _out(
            f"{len(exp.tasks) - len(bad)} of {len(exp.tasks)} tasks ok"
            + (f", {len(bad)} with problems" if bad else "")
        )
    return EXIT_FAILURE if problems else EXIT_OK


# --------------------------------------------------------------------------- run


def _resume_command(args: argparse.Namespace, run_dir: Path) -> str:
    """The command that continues this run with the same selection and repeats."""
    parts = [PROG, "run", _quote(args.config), "--resume", _quote(str(run_dir))]
    if args.arms:
        parts += ["--arms", _quote(",".join(args.arms))]
    for pattern in args.only or ():
        parts += ["--only", _quote(pattern)]
    if args.repeats is not None:
        parts += ["--repeats", str(args.repeats)]
    return " ".join(parts)


def _display_path(path: Path) -> str:
    try:
        rel = os.path.relpath(path)
    except ValueError:  # another drive on Windows
        return str(path)
    return str(path) if rel.startswith("..") else rel


@contextlib.contextmanager
def _interrupt_on_termination() -> Iterator[None]:
    """Treat Ctrl-Break / console close (Windows) and SIGTERM / SIGHUP (POSIX) like Ctrl-C.

    The handlers raise KeyboardInterrupt in the main thread, so the runner's cancellation
    path runs: agents are killed, nothing half-done is recorded, and a resume hint is shown.
    """

    def handler(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    names = ("SIGBREAK",) if os.name == "nt" else ("SIGTERM", "SIGHUP")
    previous: dict[int, Any] = {}
    if threading.current_thread() is threading.main_thread():
        for name in names:
            sig = getattr(signal, name, None)
            if sig is not None:
                with contextlib.suppress(ValueError, OSError):
                    previous[sig] = signal.signal(sig, handler)
    try:
        yield
    finally:
        for sig, old in previous.items():
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(sig, old)


def _meta_problems(meta: dict) -> list[str]:
    """Fields of run.json that the commands rely on and that are missing or malformed."""
    problems = [
        key
        for key in ("experiment", "baseline")
        if not isinstance(meta.get(key), str) or not meta.get(key)
    ]
    planned = meta.get("planned_trials")
    if isinstance(planned, bool) or not isinstance(planned, int) or planned < 0:
        problems.append("planned_trials")
    config = meta.get("config")
    if not isinstance(config, dict):
        return [*problems, "config"]
    arms = config.get("arms")
    if (
        not isinstance(arms, list)
        or not arms
        or not all(isinstance(a, dict) and isinstance(a.get("name"), str) for a in arms)
    ):
        problems.append("config.arms")
    tasks = config.get("tasks")
    if not isinstance(tasks, list) or not all(
        isinstance(t, dict) and isinstance(t.get("id"), str) for t in tasks
    ):
        problems.append("config.tasks")
    return problems


def _open_run(path_text: str) -> RunStore:
    """Open a run directory given on the command line, checking run.json is usable."""
    path = Path(path_text)
    if not path.exists():
        raise UsageError(f"run directory not found: {path_text}")
    if not path.is_dir():
        raise UsageError(f"not a directory: {path_text}")
    store = RunStore.open(path)
    problems = _meta_problems(store.meta)
    if problems:
        raise RunStoreError(
            f"{path / RUN_FILE} is incomplete (missing or invalid: {', '.join(problems)}); "
            "it was not written by this version of agent-ab or has been edited"
        )
    return store


class _Progress:
    """Formats runner progress events as aligned lines on stderr."""

    def __init__(self, exp: Experiment, quiet: bool):
        self.quiet = quiet
        self.task_w = max((len(t.id) for t in exp.tasks), default=4)
        self.arm_w = max((len(a.name) for a in exp.arms), default=4)
        self.rep_w = len(f"r{max(exp.repeats - 1, 0)}")

    def _prefix(self, ev: Any, rec: TrialRecord) -> str:
        n = len(str(ev.total))
        return (
            f"[{ev.done:>{n}}/{ev.total}] {_clean(rec.task):<{self.task_w}}  "
            f"{_clean(rec.arm):<{self.arm_w}}  {f'r{rec.repeat}':<{self.rep_w}}"
        )

    def __call__(self, ev: Any) -> None:
        rec = ev.record
        if ev.kind == "finish" and rec is not None:
            if self.quiet:
                return
            line = (
                f"{self._prefix(ev, rec)}  {rec.status:<5}  "
                f"{_fmt_seconds(rec.duration_s):>7}  {_fmt_cost(rec.cost_usd):>7}  "
                f"(spent {_fmt_cost(ev.spent_usd)})"
            )
            if rec.status == "error" or (rec.error and rec.status == "fail"):
                line += f"  {_short(rec.error, 80)}"
            _err(line)
        elif ev.kind == "retry" and rec is not None:
            if not self.quiet:
                _err(
                    f"{self._prefix(ev, rec)}  retry  attempt {rec.attempt} error: "
                    f"{_short(rec.error, 80)}"
                )
        elif ev.kind == "budget":
            _warn(ev.message)
        elif ev.kind == "info" and ev.message:
            _err(ev.message)


def cmd_run(args: argparse.Namespace) -> int:
    from agent_ab.runner import (
        RunOptions,
        _unused_run_dir,
        default_run_dir,
        plan_trials,
        run_experiment,
    )

    exp = _load(args)
    if len(exp.arms) < 2:
        # A one-arm run is a pilot: it measures baseline difficulty (and feeds `power`).
        _warn(f"only one arm ({exp.arms[0].name}): this run measures, it does not compare")
    if args.repeats is not None and args.repeats != exp.repeats:
        # repeats is part of the experiment's identity, so it must enter the fingerprint.
        exp = dataclasses.replace(exp, repeats=args.repeats)
        exp = dataclasses.replace(exp, fingerprint=compute_fingerprint(exp))

    if args.resume:
        _open_run(args.resume)
        run_dir = Path(args.resume)
    elif args.out:
        run_dir = Path(args.out)
        if run_dir.exists() and not run_dir.is_dir():
            raise UsageError(f"--out {args.out} exists and is not a directory")
        if (run_dir / RUN_FILE).exists():
            raise UsageError(
                f"{args.out} already contains a run; continue it with --resume {_quote(args.out)}"
            )
    else:
        run_dir = _unused_run_dir(default_run_dir(exp))

    def options(*, dry_run: bool, progress: Callable[[Any], None] | None) -> RunOptions:
        return RunOptions(
            jobs=args.jobs,
            budget_usd=args.budget,
            dry_run=dry_run,
            keep_workspaces=True if args.keep_workspaces else None,
            force=args.force,
            progress=progress,
        )

    jobs = args.jobs or exp.jobs
    budget = args.budget if args.budget is not None else exp.budget_usd
    planned = len(plan_trials(exp))
    arm_names = [a.name + (" (baseline)" if a.name == exp.baseline else "") for a in exp.arms]
    header = [
        ("experiment", exp.name),
        ("arms", ", ".join(arm_names)),
        ("tasks", str(len(exp.tasks))),
        ("repeats", str(exp.repeats)),
        ("trials", f"{planned} planned"),
        ("jobs", str(jobs)),
        ("budget", _budget_text(budget)),
        ("run dir", _display_path(run_dir) + (" (resume)" if args.resume else "")),
    ]
    resume_hint = _resume_command(args, run_dir)
    try:
        with _interrupt_on_termination():
            # A silent dry run first: unusable adapters or run directories fail here, before
            # the header suggests that a run is starting.
            run_experiment(
                exp, run_dir, resume=bool(args.resume), options=options(dry_run=True, progress=None)
            )
            for key, value in header:
                _err(f"{key:<11}{value}")
            if args.dry_run:
                _err("dry run: nothing will be created or run")
            _err("")
            summary = run_experiment(
                exp,
                run_dir,
                resume=bool(args.resume),
                options=options(dry_run=args.dry_run, progress=_Progress(exp, args.quiet)),
            )
    except KeyboardInterrupt:
        summary = None
    if summary is None or summary.cancelled:
        if args.dry_run or not (run_dir / RUN_FILE).exists():
            _err(f"{PROG}: interrupted")
        else:
            _err(f"{PROG}: interrupted; resume with: {resume_hint}")
        return EXIT_INTERRUPTED
    if args.dry_run:
        return EXIT_OK

    store = RunStore.open(run_dir)
    records = store.records()
    analysis = analyze(store.meta, records)
    outputs = {
        "report.html": render_html(analysis),
        "report.md": render_markdown(analysis),
        "analysis.json": render_json(analysis),
    }
    for name, text in outputs.items():
        (run_dir / name).write_text(text, encoding="utf-8", newline="\n")
    sys.stdout.write(render_text(analysis, width=_report_width()))
    sys.stdout.flush()

    _err("")
    for name in outputs:
        _err(f"wrote {_display_path(run_dir / name)}")
    remaining = summary.planned - summary.completed - summary.errors
    if summary.budget_exhausted and remaining:
        _warn(
            f"budget {_budget_text(budget)} reached with {remaining} of {summary.planned} "
            f"trials not run; raise it with --budget and resume with: {resume_hint}"
        )
    elif remaining:
        _warn(f"{remaining} of {summary.planned} trials did not finish; resume with: {resume_hint}")
    if summary.errors:
        _warn(
            f"{summary.errors} trial(s) ended in infrastructure errors after all retries "
            f"and are excluded from the statistics; see: {PROG} status "
            f"{_quote(str(run_dir))}"
        )
    if summary.completed == 0 and summary.planned and not summary.budget_exhausted:
        return EXIT_FAILURE
    return EXIT_OK


# --------------------------------------------------------------------------- report


def _check_out_path(text: str) -> None:
    # Windows maps these names to devices in every directory, whatever the extension, so
    # writing "nul.html" silently discards the report and "con.md" floods the console.
    for part in re.split(r"[\\/]", text):
        stem = part.split(".", 1)[0].rstrip(" ").lower()
        if stem in _RESERVED_NAMES:
            raise UsageError(f"--out {text!r} uses the reserved device name {part!r}")


def cmd_report(args: argparse.Namespace) -> int:
    if args.out is not None:
        _check_out_path(args.out)
    store = _open_run(args.run_dir)
    try:
        analysis = analyze(
            store.meta, store.records(), baseline=args.baseline, alpha=args.alpha, seed=args.seed
        )
    except ValueError as e:
        raise UsageError(str(e)) from e
    if args.format == "text":
        width = _report_width() if args.out is None else 100
        text = render_text(analysis, width=width)
    elif args.format == "md":
        text = render_markdown(analysis)
    elif args.format == "json":
        text = render_json(analysis)
    else:
        text = render_html(analysis)
    if not text.endswith("\n"):
        text += "\n"

    if args.out is None:
        sys.stdout.write(text)
        sys.stdout.flush()
        return EXIT_OK
    out = Path(args.out)
    if out.is_dir() or args.out.endswith(("/", "\\")):
        out = out / _FORMAT_FILES[args.format]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    _err(f"wrote {_display_path(out)}")
    return EXIT_OK


# --------------------------------------------------------------------------- status


def _max_retries(meta: dict) -> int:
    value = (meta.get("config") or {}).get("max_retries")
    return value if isinstance(value, int) and value >= 0 else 2


def _planned_ids(meta: dict) -> list[str]:
    """Trial ids implied by run.json's resolved config (empty if it cannot be read)."""
    cfg = meta.get("config") or {}
    try:
        tasks = [t["id"] for t in cfg.get("tasks") or []]
        arms = [a["name"] for a in cfg.get("arms") or []]
        repeats = int(cfg.get("repeats") or 0)
    except (KeyError, TypeError, ValueError):
        return []
    return [trial_id(t, a, r) for t in tasks for a in arms for r in range(repeats)]


def cmd_status(args: argparse.Namespace) -> int:
    store = _open_run(args.run_dir)
    meta = store.meta
    records = store.records()
    finals = store.final_records()
    max_retries = _max_retries(meta)
    planned = int(meta.get("planned_trials") or 0)

    done = [r for r in finals.values() if is_done(r, max_retries)]
    passes = sum(r.status == "pass" for r in done)
    fails = sum(r.status == "fail" for r in done)
    errors = sum(r.status == "error" for r in done)
    retrying = len(finals) - len(done)
    remaining = max(planned - len(done), 0)
    finished = [r.finished_at for r in records if r.finished_at]

    _out(f"Run: {store.run_dir}")
    _out(
        f"Experiment: {meta.get('experiment', '?')}   baseline: {meta.get('baseline', '?')}   "
        f"created: {meta.get('created_at', '?')}"
    )
    _out(
        f"Trials: {len(done)}/{planned} done ({passes} pass, {fails} fail, {errors} error), "
        f"{remaining} remaining" + (f" ({retrying} awaiting a retry)" if retrying else "")
    )
    spend = _total(r.cost_usd for r in records)
    _out(f"Attempts recorded: {len(records)}   spend: {_fmt_cost(spend)}")
    _out(f"Last activity: {max(finished) if finished else 'none yet'}")

    arm_order = [
        a.get("name") for a in (meta.get("config") or {}).get("arms") or [] if isinstance(a, dict)
    ]
    for r in finals.values():
        if r.arm not in arm_order:
            arm_order.append(r.arm)
    per_arm_planned = planned // len(arm_order) if arm_order else 0
    rows = []
    for arm in arm_order:
        arm_done = [r for r in done if r.arm == arm]
        cost = _total(r.cost_usd for r in records if r.arm == arm)
        count = f"{len(arm_done)}/{per_arm_planned}" if per_arm_planned else str(len(arm_done))
        rows.append(
            [
                str(arm),
                count,
                str(sum(r.status == "pass" for r in arm_done)),
                str(sum(r.status == "fail" for r in arm_done)),
                str(sum(r.status == "error" for r in arm_done)),
                _fmt_cost(cost),
            ]
        )
    if rows:
        _out("")
        _out(_table(["arm", "done", "pass", "fail", "error", "spend"], rows, right=(1, 2, 3, 4, 5)))

    errored = sorted((r for r in finals.values() if r.status == "error"), key=lambda r: r.trial_id)
    if errored:
        _out("")
        _out("Errors (last attempt):")
        for r in errored[:10]:
            state = "final" if is_done(r, max_retries) else "will retry on resume"
            _out(f"  {r.trial_id} (attempt {r.attempt}, {state}): {_short(r.error, 90)}")
        if len(errored) > 10:
            _out(f"  ... and {len(errored) - 10} more")
    reports = [
        n for n in ("report.html", "report.md", "analysis.json") if (store.run_dir / n).exists()
    ]
    _out("")
    _out(f"Reports: {', '.join(reports) if reports else 'not written yet'}")
    return EXIT_OK


# --------------------------------------------------------------------------- show


def _artifact_dir(store: RunStore, rec: TrialRecord) -> Path | None:
    """The attempt's artifact folder, or None if its recorded path leaves the run directory."""
    if not rec.artifacts:
        return store.run_dir / TRIALS_DIR / rec.trial_id / f"attempt-{rec.attempt}"
    root = store.run_dir.resolve()
    try:
        path = (root / rec.artifacts).resolve()
    except (OSError, ValueError):
        return None
    return path if path.is_relative_to(root) else None


def cmd_show(args: argparse.Namespace) -> int:
    store = _open_run(args.run_dir)
    tid = args.trial_id
    attempts = sorted((r for r in store.records() if r.trial_id == tid), key=lambda r: r.attempt)
    if not attempts:
        recorded = sorted({r.trial_id for r in store.records()})
        planned = _planned_ids(store.meta)
        if tid in planned:
            raise UsageError(f"trial {tid!r} has not run yet")
        close = difflib.get_close_matches(
            tid, sorted(set(recorded) | set(planned)), n=5, cutoff=0.5
        )
        hint = f"; did you mean: {', '.join(close)}" if close else ""
        raise UsageError(f"no trial {tid!r} in {args.run_dir}{hint}")

    final = attempts[-1]
    _out(json.dumps(final.to_dict(), indent=2, sort_keys=True))
    if len(attempts) > 1:
        _out("")
        _out(f"Attempts ({len(attempts)}):")
        for r in attempts:
            _out(
                f"  attempt {r.attempt}  {r.status:<5}  {r.finished_at or '-'}  "
                f"{_short(r.error, 80) if r.error else ''}".rstrip()
            )

    _out("")
    _out("Artifacts:")
    for r in attempts:
        adir = _artifact_dir(store, r)
        if adir is None:
            _out(f"  attempt {r.attempt}: (not listed)")
            _warn(
                f"attempt {r.attempt} records artifacts at {r.artifacts!r}, outside the run "
                "directory; not listing it"
            )
            continue
        _out(f"  attempt {r.attempt}: {adir}")
        if adir.is_dir():
            for dirpath, dirnames, filenames in os.walk(adir):  # does not follow links
                dirnames.sort()
                base = Path(dirpath)
                for name in sorted(filenames):
                    _out(f"    {(base / name).relative_to(adir).as_posix()}")
        else:
            _out("    (missing)")
    final_dir = _artifact_dir(store, final) if final.artifacts else None
    ws_file = final_dir / "workspace.txt" if final_dir is not None else None
    if ws_file is not None and ws_file.is_file():
        _out(f"Workspace: {ws_file.read_text(encoding='utf-8', errors='replace').strip()}")
    return EXIT_OK


# --------------------------------------------------------------------------- power


def cmd_power(args: argparse.Namespace) -> int:
    try:
        options = power.parse_options(
            effect=args.effect,
            tasks=args.tasks,
            repeats=args.repeats,
            alpha=args.alpha,
            sims=args.sims,
            seed=args.seed,
        )
    except ValueError as e:
        raise UsageError(str(e)) from e
    if args.run_dir is None:
        model = power.beta_model()
    else:
        store = _open_run(args.run_dir)
        try:
            model = power.pilot_model(store.meta, store.records())
        except ValueError as e:
            raise UsageError(str(e)) from e
    for warning in model.warnings:
        _warn(warning)

    started = time.monotonic()

    def progress(done: int, total: int, row: power.DesignResult) -> None:
        if time.monotonic() - started > 2 and done < total:
            _err(
                f"[{done}/{total}] effect +{row.effect:g} pts, tasks {row.tasks}, "
                f"repeats {row.repeats}"
            )

    plan = power.run_plan(model, options, progress=progress)
    sys.stdout.write(power.render(plan, args.format))
    sys.stdout.flush()
    return EXIT_OK


# --------------------------------------------------------------------------- main


_COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "init": cmd_init,
    "validate": cmd_validate,
    "run": cmd_run,
    "report": cmd_report,
    "status": cmd_status,
    "show": cmd_show,
    "power": cmd_power,
}


def _error(message: str, stream: TextIO | None = None) -> None:
    print(_clean(f"{PROG}: error: {message}"), file=stream or sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    """Run the CLI with ``argv`` (default: ``sys.argv[1:]``) and return the exit code."""
    _setup_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse: --help/--version exit 0, usage errors exit 2
        return e.code if isinstance(e.code, int) else EXIT_USAGE
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    debug = os.environ.get("AGENT_AB_DEBUG", "").strip() not in ("", "0")
    try:
        return _COMMANDS[args.command](args)
    except KeyboardInterrupt:
        _err(f"{PROG}: interrupted")
        return EXIT_INTERRUPTED
    except (ConfigError, UsageError) as e:
        if debug:
            traceback.print_exc()
        _error(str(e))
        return EXIT_USAGE
    except AgentABError as e:
        if debug:
            traceback.print_exc()
        _error(str(e))
        return EXIT_FAILURE
    except OSError as e:
        if debug:
            traceback.print_exc()
        _error(str(e))
        return EXIT_FAILURE
    except Exception as e:
        if debug:
            traceback.print_exc()
        _error(f"unexpected {type(e).__name__}: {e} (set AGENT_AB_DEBUG=1 for a traceback)")
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
