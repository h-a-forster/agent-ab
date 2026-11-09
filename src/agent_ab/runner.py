"""Execute an experiment: plan trials, run them concurrently, retry, budget, resume, cancel.

Every attempt runs in a fresh workspace and is appended to the run store as soon as it
finishes, so the log on disk is always the complete truth. Infrastructure errors are retried;
a budget or repeated isolation breaches stop new launches; Ctrl-C kills running agents and
records nothing half-done.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import random
import re
import threading
import traceback
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agent_ab import __version__
from agent_ab.adapters import get_adapter
from agent_ab.adapters.base import Adapter
from agent_ab.errors import (
    AdapterError,
    AgentABError,
    GitDirAlteredError,
    GitTimeoutError,
    HostError,
    RunStoreError,
    WorkspaceError,
    is_host_failure,
)
from agent_ab.model import (
    AgentUsage,
    Arm,
    Experiment,
    ProcResult,
    Task,
    TrialContext,
    TrialRecord,
    TrialSpec,
    trial_seed,
)
from agent_ab.proc import build_env, run_process
from agent_ab.store import (
    IN_USE_DIR,
    MAX_COST_USD,
    TRIALS_DIR,
    RunLock,
    RunStore,
    check_new_run_dir,
    is_done,
    retry_bases,
    utc_now,
)
from agent_ab.workspace import (
    Workspace,
    _is_link,
    added_enough_to_stall_git,
    apply_patch,
    create_workspace,
    destroy_workspace,
    diff_stats,
    install_checks,
    rebaseline,
    resolve_workspace_root,
    run_check,
    run_command,
    workspace_prefix,
)

_WAIT_S = 0.2  # main-thread wait slice; short so Ctrl-C is delivered promptly on Windows
# Isolation breaches, each with no graded trial of its arm since, that stop the run. A leak comes
# from the machine, so every further trial would pay for an attempt the statistics exclude.
_MAX_CONSECUTIVE_BREACHES = 3
# Infrastructure errors in one arm, with none of its trials graded between them, that stop the run.
# In an outage every further attempt would only use up retries the trials need afterwards.
_MAX_CONSECUTIVE_ERRORS = 10

ProgressKind = Literal["start", "finish", "retry", "budget", "halt", "info"]


@dataclass
class ProgressEvent:
    """One scheduling event, reported from the calling thread."""

    kind: ProgressKind
    trial_id: str | None = None
    attempt: int | None = None
    record: TrialRecord | None = None
    done: int = 0  # trials that need no more attempts (includes earlier sessions)
    total: int = 0  # planned trials
    spent_usd: float = 0.0  # recorded spend including earlier sessions
    message: str = ""


@dataclass
class RunOptions:
    """Per-invocation settings. Non-None values override the experiment's own."""

    jobs: int | None = None
    budget_usd: float | None = None
    dry_run: bool = False
    keep_workspaces: bool | None = None
    force: bool = False  # resume even if the experiment fingerprint changed
    retry_errors: bool = False  # resume: give trials with exhausted errors a fresh set of retries
    progress: Callable[[ProgressEvent], None] | None = field(default=None, repr=False)


@dataclass
class RunSummary:
    """Outcome of ``run_experiment``. Counts cover the whole run, earlier sessions included."""

    run_dir: Path
    planned: int
    completed: int  # trials whose final attempt passed or failed
    errors: int  # trials whose retries are exhausted with an infrastructure error
    # planned - completed - errors = trials still open: not reached, awaiting a retry or breached
    skipped_budget: int  # trials left unfinished because the budget ran out
    cancelled: bool
    total_cost_usd: float
    budget_exhausted: bool
    isolation_halt: str | None = None  # why repeated isolation breaches stopped the run
    infra_halt: str | None = None  # why repeated infrastructure errors stopped the run
    open_breaches: int = 0  # trials this session left open after an isolation breach


class _Cancelled(Exception):
    """Internal: the attempt was interrupted and must not be recorded."""


class _GradingBroken(Exception):
    """Internal: a grading step failed. ``host``: the machine is known to be the cause."""

    def __init__(self, message: str, *, host: bool = False):
        super().__init__(message)
        self.host = host


# --------------------------------------------------------------------------- planning


def plan_trials(exp: Experiment) -> list[TrialSpec]:
    """Every (task, arm, repeat) cell, in a deterministic order derived from the experiment seed.

    The (task, repeat) blocks are shuffled so drift (provider load, rate limits) does not line
    up with a task. Within a block the arms sit next to each other, in an order drawn per block
    so no arm systematically goes first. Adjacent arms see similar conditions, which keeps cost
    and time ratios from being confounded by cache warmth and load drift.
    """
    rng = random.Random(exp.seed)
    blocks = [(task, r) for task in exp.tasks for r in range(exp.repeats)]
    rng.shuffle(blocks)
    plan: list[TrialSpec] = []
    for task, r in blocks:
        arms = list(exp.arms)
        rng.shuffle(arms)
        plan.extend(TrialSpec(task=task, arm=arm, repeat=r) for arm in arms)
    return plan


def default_run_dir(exp: Experiment) -> Path:
    """``<exp.root>/runs/<name>-<UTC YYYYmmdd-HHMMSS>``."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path(exp.root) / "runs" / f"{exp.name}-{stamp}"


# --------------------------------------------------------------------------- one attempt


def _build_prompt(spec: TrialSpec) -> str:
    parts = (spec.arm.prompt_prefix, spec.task.prompt, spec.arm.prompt_suffix)
    return "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()


def _attempt_seed(exp: Experiment, tid: str, attempt: int) -> int:
    # Retries get a fresh seed: an agent seeded identically would just repeat the same failure.
    key = tid if attempt == 0 else f"{tid}/attempt-{attempt}"
    return trial_seed(exp.seed, key)


def _exception_summary(e: BaseException) -> str:
    text = "".join(traceback.format_exception_only(type(e), e)).strip()
    frames = traceback.extract_tb(e.__traceback__)
    if frames:
        f = frames[-1]
        text += f" (at {Path(f.filename).name}:{f.lineno} in {f.name})"
    return text[:2000]


class _LiveDirs:
    """Directories one attempt created outside the run directory, listed inside it.

    The list goes once they are all gone (or kept on purpose). What stays says what a crash or a
    failed delete left behind, also when the attempt folder itself was removed, and the next
    resume removes it (``_sweep_leftovers``).
    """

    def __init__(self, store: RunStore, tid: str, attempt: int):
        self.file = store.run_dir / IN_USE_DIR / f"{tid}.a{attempt}.txt"
        self.added: set[str] = set()
        self.leaked: set[str] = set()

    def add(self, path: Path) -> None:
        with contextlib.suppress(OSError):
            self.file.parent.mkdir(exist_ok=True)
            with open(self.file, "a", encoding="utf-8", newline="\n") as f:
                f.write(f"{path}\t{_dir_identity(path)}\n")
            self.added.add(str(path))

    def close(self) -> None:
        # An unrecorded attempt re-runs under its number, so the file can hold what a sweep left.
        with contextlib.suppress(OSError):
            lines = self.file.read_text(encoding="utf-8").splitlines()
            done = self.added - self.leaked
            left = [x for x in lines if x.rpartition("\t")[0] not in done]
            if left:
                self.file.write_text(
                    "".join(f"{x}\n" for x in left), encoding="utf-8", newline="\n"
                )
            else:
                self.file.unlink()


def _dir_identity(path: Path) -> str:
    st = os.lstat(path)
    return f"{st.st_dev}:{st.st_ino}"


def _created_by_listing(line: str, label: str, run_dir: Path) -> Path | None:
    """The folder a line names, if it can only be the one the attempt recorded when it made it.

    The list is in reach of agents and of mistakes, so all of this must hold: the name the attempt
    gave it, the identity it had then, not a link, and not the run directory or a folder holding it.
    """
    path_text, _, identity = line.rpartition("\t")
    path = Path(path_text)
    try:
        return (
            path
            if path.is_absolute()
            and path.name.startswith(label)
            and not _is_link(path)
            and _dir_identity(path) == identity
            and not run_dir.is_relative_to(path.resolve())
            else None
        )
    except OSError:
        return None


def _sweep_leftovers(run_dir: Path) -> None:
    """Remove what earlier sessions left. Call holding the run lock: nothing here is in use.

    Never removes what it cannot prove an attempt of this run created. That stays listed, and
    ``status`` says so, for a person to look at.
    """
    folder = run_dir / IN_USE_DIR
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        named = re.fullmatch(r"(.+)\.a(\d+)\.txt", entry.name)
        if named is None:
            continue
        label = workspace_prefix(f"{named[1]}-a{named[2]}")
        with contextlib.suppress(OSError):
            left: list[str] = []
            for line in entry.read_text(encoding="utf-8").splitlines():
                path = _created_by_listing(line, label, run_dir)
                gone = not os.path.lexists(line.rpartition("\t")[0] or line)
                if not gone and (path is None or not destroy_workspace(Workspace(path=path))):
                    left.append(line)
            if left:
                entry.write_text("".join(f"{x}\n" for x in left), encoding="utf-8", newline="\n")
            else:
                entry.unlink()
    _drop_empty(folder)


def _drop_empty(folder: Path) -> None:
    with contextlib.suppress(OSError):
        folder.rmdir()


def _note_leak(art: Path | None, ws: Workspace, live: _LiveDirs) -> None:
    # Something still holds files in the workspace; leave a pointer so it can be cleaned up.
    # One line per workspace: the agent's and the grading copy can both leak.
    live.leaked.add(str(ws.path))
    if art is not None and art.is_dir():
        with (
            contextlib.suppress(OSError),
            open(art / "workspace-leaked.txt", "a", encoding="utf-8", newline="\n") as f,
        ):
            f.write(str(ws.path) + "\n")


def _remove_dir(path: Path) -> None:
    destroy_workspace(Workspace(path=path))  # robust, retrying, never raises


def _fresh_attempt_dir(store: RunStore, tid: str, attempt: int) -> Path:
    # A crash or Ctrl-C in an earlier session may have left an unrecorded attempt folder
    # behind; its files must not be mistaken for this attempt's.
    stale = store.run_dir / TRIALS_DIR / tid / f"attempt-{attempt}"
    if stale.exists() and not destroy_workspace(Workspace(path=stale)):
        raise WorkspaceError(f"cannot clear the stale attempt folder {stale}")
    return store.attempt_dir(tid, attempt)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def _proc_failure(what: str, r: ProcResult, timeout_s: float | None) -> str | None:
    """Describe why a setup/check process did not complete normally, or None if it did."""
    if r.start_error:
        return f"{what} could not start: {r.start_error}"
    if r.timed_out:
        return f"{what} timed out after {timeout_s:g}s"
    return None


def _check_cancel(cancel: threading.Event, r: ProcResult | None = None) -> None:
    if cancel.is_set() and (r is None or not r.timed_out):
        raise _Cancelled


_MAX_MODELS = 20
_LEAK_CHECKS = ("clean", "leaked", "unverified")
_MAX_VERSION = 100
_MAX_COUNT = 10**12  # tokens/turns above this are not plausible for one attempt
_USAGE_COUNTS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
                 "turns")  # fmt: skip


def _sane_count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_COUNT:
        return value
    return None


def _sane_cost(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Compare before converting: float() of a huge int raises, and NaN fails every comparison.
    if not 0 <= value <= MAX_COST_USD:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _short_repr(value: object) -> str:
    try:
        text = repr(value)
    except Exception:  # e.g. an int too large to print
        text = f"<unprintable {type(value).__name__}>"
    return text if len(text) <= 80 else text[:77] + "..."


def _copy_usage(rec: TrialRecord, usage: AgentUsage) -> list[str]:
    """Copy plausible usage values into ``rec``; return a note for each value dropped.

    Usage comes from agent output, which is untrusted: an absurd number would poison the
    budget and every statistic, while an unknown value merely leaves a gap.
    """
    dropped: list[str] = []
    cost = _sane_cost(usage.cost_usd)
    if cost is None and usage.cost_usd is not None:
        dropped.append(f"cost_usd: {_short_repr(usage.cost_usd)}")
    rec.cost_usd = cost
    rec.isolation_breach = usage.isolation_breach
    rec.leak_check = usage.leak_check if usage.leak_check in _LEAK_CHECKS else None
    _copy_identity(rec, usage)
    for name in _USAGE_COUNTS:
        raw = getattr(usage, name)
        value = _sane_count(raw)
        if value is None and raw is not None:
            dropped.append(f"{name}: {_short_repr(raw)}")
        setattr(rec, name, value)
    return dropped


def _copy_identity(rec: TrialRecord, usage: AgentUsage) -> None:
    """Copy the model, version and start-up summary reported by the agent, if well formed."""
    models = usage.models
    if isinstance(models, list) and all(isinstance(m, str) for m in models) and models:
        rec.models = sorted(set(models))[:_MAX_MODELS]
    version = usage.agent_version
    if isinstance(version, str) and version.strip():
        rec.agent_version = version.strip()[:_MAX_VERSION]
    init = usage.agent_init
    if isinstance(init, dict):
        try:
            json.dumps(init, allow_nan=False)
        except (TypeError, ValueError):
            pass
        else:
            rec.agent_init = init


# Root-level instruction files coding agents read from the workspace on their own (Claude Code,
# Codex and other AGENTS.md readers). Hashed after setup, as the agent finds them. Not a
# complete list: rules, skills, settings and nested instruction files are not hashed.
INSTRUCTION_FILES = ("CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md", "AGENTS.md")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _instruction_hashes(ws: Workspace, extra: list[Path]) -> dict[str, str]:
    """SHA-256 of each instruction file the agent receives, keyed by where it comes from."""
    found: dict[str, str] = {}
    for rel in INSTRUCTION_FILES:
        digest = _file_sha256(ws.path / rel)
        if digest is not None:
            found[rel] = digest
    for path in extra:
        digest = _file_sha256(Path(path))
        if digest is not None:
            found[f"agent:{Path(path).name}"] = digest
    return found


def _write_usage_warning(art: Path, notes: list[str]) -> None:
    with (
        contextlib.suppress(OSError),
        open(art / "usage_warning.txt", "a", encoding="utf-8", newline="\n") as f,
    ):
        f.write("".join(n + "\n" for n in notes))


def _probe_versions(exp: Experiment) -> dict[str, str]:
    """Agent CLI version per arm, for the arms whose adapter can tell."""
    found: dict[str, str] = {}
    for arm in exp.arms:
        try:
            version = get_adapter(arm.agent.adapter).version(arm.agent)
        except Exception:  # a probe must never stop a run
            continue
        if isinstance(version, str) and version.strip():
            found[arm.name] = version.strip()[:_MAX_VERSION]
    return found


def _parse_usage(adapter: Adapter, ctx: TrialContext, result: ProcResult, art: Path) -> AgentUsage:
    """Run the adapter's parser, treating any failure as "usage unknown".

    The agent did run, so a parser crash on hostile or unexpected output must not turn the
    attempt into an infrastructure error (which would be retried and excluded).
    """
    try:
        usage = adapter.parse(ctx, result)
    except Exception as e:
        _write_usage_warning(art, [f"usage could not be parsed: {_exception_summary(e)}"])
        return AgentUsage(leak_check="unverified")
    if not isinstance(usage, AgentUsage):
        _write_usage_warning(art, [f"adapter returned {type(usage).__name__}; usage ignored"])
        return AgentUsage(leak_check="unverified")
    return usage


def _execute(
    exp: Experiment,
    spec: TrialSpec,
    attempt: int,
    rec: TrialRecord,
    art: Path,
    ws: Workspace,
    cancel: threading.Event,
    live: _LiveDirs,
    keep: bool = False,
) -> None:
    """The attempt pipeline after the workspace exists. Fills ``rec`` in place."""
    task, arm = spec.task, spec.arm
    agent_timeout = task.timeout_s if task.timeout_s is not None else exp.timeout_s
    check_timeout = (
        task.check_timeout_s if task.check_timeout_s is not None else exp.check_timeout_s
    )

    if task.setup is not None:
        r = run_command(
            task.setup, ws, timeout_s=agent_timeout,
            stdout_path=art / "setup.stdout", stderr_path=art / "setup.stderr", cancel=cancel,
        )  # fmt: skip
        _check_cancel(cancel, r)
        problem = _proc_failure("setup", r, agent_timeout)
        if problem is None and r.exit_code != 0:
            problem = f"setup failed with exit code {r.exit_code} (see setup.stderr)"
        if problem:
            rec.error = problem
            return
        rebaseline(ws)

    prompt = _build_prompt(spec)
    _write_text(art / "prompt.md", prompt + "\n")
    adapter = get_adapter(arm.agent.adapter)
    ctx = TrialContext(
        spec=arm.agent, task=task, arm=arm, repeat=spec.repeat, attempt=attempt, prompt=prompt,
        workspace=ws.path, artifacts=art, seed=_attempt_seed(exp, spec.id, attempt),
        root=exp.root,
    )  # fmt: skip
    inv = adapter.build(ctx)
    for path in inv.temp_dirs:
        live.add(path)
    try:
        rec.prompt_sha256 = _sha256(prompt.encode("utf-8"))
        rec.instructions_sha256 = _instruction_hashes(ws, inv.instruction_files) or None
        result = run_process(
            inv.argv,
            cwd=inv.cwd or ws.path,
            env=build_env({**arm.agent.env, **inv.env}, base=inv.base_env),
            timeout_s=agent_timeout,
            stdout_path=art / "agent.stdout",
            stderr_path=art / "agent.stderr",
            stdin_text=inv.stdin,
            cancel=cancel,
        )
    finally:
        for path in inv.temp_dirs:
            if not destroy_workspace(Workspace(path=path)):
                _note_leak(art, Workspace(path=path), live)
    _check_cancel(cancel, result)
    rec.agent_exit_code = result.exit_code
    rec.agent_timed_out = result.timed_out
    rec.duration_s = round(result.duration_s, 3)
    if result.start_error:
        rec.error = f"agent could not start: {result.start_error}"
        return
    usage = _parse_usage(adapter, ctx, result, art)
    dropped = _copy_usage(rec, usage)
    if dropped:
        _write_usage_warning(art, ["implausible usage values dropped:", *dropped])
    if usage.infra_error or usage.isolation_breach:
        rec.error = f"infrastructure error: {usage.infra_error or 'isolation breach'}"
        return

    try:
        _grade(exp, rec, art, ws, spec, result, agent_timeout, check_timeout, cancel, live, keep)
    except _Cancelled:
        raise
    except Exception as e:
        if cancel.is_set():
            raise _Cancelled from e
        broken = isinstance(e, _GradingBroken)
        message = (
            str(e) if broken else f"grading failed after the agent ran: {_exception_summary(e)}"
        )
        # What the agent did to its workspace that breaks grading (links over check paths,
        # unreadable files) is its outcome: retrying would bill again and excluding would hide
        # sabotage. So a copy it never touched goes through every step that does not need its
        # changes (snapshot, setup, checks, starting the check): what fails there, or what is
        # known to be the machine (a full disk), is an infrastructure error.
        host = e.host if broken else isinstance(e, HostError) or is_host_failure(e)
        machine = "the machine" if host else _control_problem(
            exp, spec, attempt, art, agent_timeout, check_timeout, cancel, live
        )  # fmt: skip
        if machine:
            rec.status, rec.passed = "error", None
            rec.error = f"{message} (not the agent's doing: {machine})"
        else:
            rec.status, rec.passed = "fail", False
            rec.error = message
        with contextlib.suppress(OSError):
            _write_text(art / "traceback.txt", traceback.format_exc())


def _prepare_pristine(
    task: Task,
    ws: Workspace,
    art: Path,
    timeout_s: float,
    cancel: threading.Event,
    what: str,
    prefix: str,
) -> str | None:
    """Run the task's setup in a fresh copy and snapshot the result; return what went wrong."""
    if task.setup is None:
        return None
    r = run_command(
        task.setup, ws, timeout_s=timeout_s,
        stdout_path=art / f"{prefix}.stdout", stderr_path=art / f"{prefix}.stderr", cancel=cancel,
    )  # fmt: skip
    _check_cancel(cancel, r)
    problem = _proc_failure(f"setup of {what}", r, timeout_s)
    if problem is None and r.exit_code != 0:
        problem = f"setup of {what} failed with exit code {r.exit_code} (see {prefix}.stderr)"
    if problem:
        return problem
    try:
        rebaseline(ws)
    except WorkspaceError as e:
        return f"cannot snapshot {what} after setup: {e}"
    return None


def _control_problem(
    exp: Experiment,
    spec: TrialSpec,
    attempt: int,
    art: Path,
    agent_timeout: float,
    check_timeout: float,
    cancel: threading.Event,
    live: _LiveDirs,
) -> str | None:
    """Why grading also breaks on a copy of the task the agent never touched, or None.

    Only whether the check can start matters here: on an unsolved task it is expected to fail.
    """
    task = spec.task
    try:
        ws = create_workspace(
            task, spec.arm, root=exp.workspace_root, label=f"{spec.id}-a{attempt}-control"
        )
    except WorkspaceError as e:
        return str(e)
    live.add(ws.path)
    try:
        problem = _prepare_pristine(
            task, ws, art, agent_timeout, cancel, "the control copy", "control-setup"
        )
        if problem:
            return problem
        install_checks(ws, task)
        outcome = run_check(
            task.check, ws, timeout_s=check_timeout,
            stdout_path=art / "control-check.stdout", stderr_path=art / "control-check.stderr",
            report_path=art / "control-check-report.json", cancel=cancel,
        )  # fmt: skip
        _check_cancel(cancel, outcome.proc)
        return outcome.proc.start_error
    except _Cancelled:
        raise
    except Exception as e:
        return _exception_summary(e)
    finally:
        if not destroy_workspace(ws):
            _note_leak(art, ws, live)


def _agent_bloated_workspace(
    exp: Experiment,
    spec: TrialSpec,
    attempt: int,
    art: Path,
    ws: Workspace,
    timeout_s: float,
    cancel: threading.Event,
    live: _LiveDirs,
) -> bool:
    """Whether what the agent added explains git timing out, measured against a clean copy."""
    try:
        copy = create_workspace(
            spec.task, spec.arm, root=exp.workspace_root, label=f"{spec.id}-a{attempt}-size"
        )
    except WorkspaceError:
        return False
    live.add(copy.path)
    try:
        problem = _prepare_pristine(
            spec.task, copy, art, timeout_s, cancel, "the size copy", "size-setup"
        )
        return problem is None and added_enough_to_stall_git(Path(ws.path), Path(copy.path))
    finally:
        if not destroy_workspace(copy):
            _note_leak(art, copy, live)


def _grade(
    exp: Experiment,
    rec: TrialRecord,
    art: Path,
    ws: Workspace,
    spec: TrialSpec,
    result: ProcResult,
    agent_timeout: float,
    check_timeout: float,
    cancel: threading.Event,
    live: _LiveDirs,
    keep: bool,
) -> None:
    """Diff, rebuild a clean copy with the agent's diff, install the checks and run them.

    Fills ``rec`` in place. The checks never run in the workspace the agent edited: a fresh
    workspace is built from the pristine task (with the arm's removals and overlay and the
    task's setup), the agent's recorded diff is applied to it, and the hidden checks go on
    top. Without git there is no diff to apply, and the checks run in the agent's workspace.
    """
    task = spec.task
    # Measured before the checks are copied in so they never count as agent changes.
    patch = art / "diff.patch"
    stats: tuple[int, int, int] | None = None
    git_dir_altered = False
    diff_error: WorkspaceError | None = None
    try:
        stats = diff_stats(ws, patch)
    except GitDirAlteredError:
        git_dir_altered = True
    except WorkspaceError as e:
        diff_error = e
    except OSError as e:
        rec.error = f"cannot write the agent's diff: {e}"  # infrastructure, not the agent
        return
    if stats is not None:
        rec.files_changed, rec.lines_added, rec.lines_removed = stats
    rec.grading = "agent-workspace" if ws.baseline_commit is None else "clean-copy"

    if result.timed_out and exp.timeout_is_failure:
        rec.status, rec.passed = "fail", False
        rec.error = f"agent timed out after {agent_timeout:g}s"
        return

    if ws.baseline_commit is None:
        _run_checks(exp, rec, art, ws, task, check_timeout, cancel)
        return
    if git_dir_altered:
        rec.status, rec.passed = "fail", False
        rec.error = "the agent's changes could not be recorded (its .git directory was altered)"
        return
    if diff_error is not None:
        host = isinstance(diff_error, HostError)
        if isinstance(diff_error, GitTimeoutError):
            host = not _agent_bloated_workspace(
                exp, spec, rec.attempt, art, ws, agent_timeout, cancel, live
            )
        raise _GradingBroken(f"the agent's changes could not be recorded: {diff_error}", host=host)
    try:
        grade_ws = create_workspace(
            task, spec.arm, root=exp.workspace_root, label=f"{spec.id}-a{rec.attempt}-grade"
        )
    except WorkspaceError as e:
        rec.error = f"cannot create the grading copy: {e}"  # infrastructure, not the agent
        return
    live.add(grade_ws.path)
    try:
        if keep:
            try:
                _write_text(art / "grade-workspace.txt", str(grade_ws.path) + "\n")
            except OSError as e:
                rec.error = f"cannot write grade-workspace.txt: {e}"  # infrastructure
                return
        problem = _prepare_pristine(
            task, grade_ws, art, agent_timeout, cancel, "the grading copy", "grade-setup"
        )
        if problem:
            # The grading copy is pristine, so this is not the agent's doing.
            rec.error = problem
            return
        try:
            apply_patch(grade_ws, patch)
        except HostError as e:
            raise _GradingBroken(f"the agent's diff could not be applied: {e}", host=True) from e
        except WorkspaceError as e:
            rec.status, rec.passed = "fail", False
            rec.error = f"the agent's diff does not apply to a clean copy of the task: {e}"
            return
        _run_checks(exp, rec, art, grade_ws, task, check_timeout, cancel)
    finally:
        if (cancel.is_set() or not keep) and not destroy_workspace(grade_ws):
            _note_leak(art, grade_ws, live)


def _run_checks(
    exp: Experiment,
    rec: TrialRecord,
    art: Path,
    ws: Workspace,
    task: Task,
    check_timeout: float,
    cancel: threading.Event,
) -> None:
    """Install the hidden checks in ``ws`` and run them. Fills ``rec`` in place."""
    install_checks(ws, task)
    outcome = run_check(
        task.check, ws, timeout_s=check_timeout,
        stdout_path=art / "check.stdout", stderr_path=art / "check.stderr",
        report_path=art / "check-report.json", cancel=cancel,
    )  # fmt: skip
    check = outcome.proc
    _check_cancel(cancel, check)
    rec.check_exit_code = check.exit_code
    rec.check_timed_out = check.timed_out
    rec.check_duration_s = round(check.duration_s, 3)
    if check.start_error:
        # An agent that deleted the workspace or a script the check runs ends up here too.
        raise _GradingBroken(f"check could not start: {check.start_error}", host=check.host_error)
    if check.timed_out:
        rec.status, rec.passed = "fail", False
        rec.error = f"check timed out after {check_timeout:g}s"
        return
    if outcome.problem:
        rec.error = outcome.problem
    rec.status = "pass" if outcome.passed else "fail"
    rec.passed = rec.status == "pass"


def run_trial(
    exp: Experiment,
    spec: TrialSpec,
    attempt: int,
    store: RunStore,
    cancel: threading.Event,
    *,
    keep_workspaces: bool | None = None,
    concurrency: int | None = None,
    agent_version: str | None = None,
    retries_used: int | None = None,
) -> TrialRecord:
    """Run one attempt of one trial and return its record. Never raises.

    The record is written to ``record.json`` in the attempt folder but not appended to the
    log; the scheduler does that. If ``cancel`` is set mid-attempt the attempt folder is
    removed and the returned record has status ``error`` and error ``"cancelled"``; such a
    record must not be stored. ``keep_workspaces`` defaults to the experiment's setting.
    ``concurrency`` (trials in flight, this one included) is recorded as given, as is
    ``agent_version`` (probed once per arm); a version the agent reports itself replaces it.
    """
    keep = exp.keep_workspaces if keep_workspaces is None else keep_workspaces
    rec = TrialRecord(
        trial_id=spec.id, task=spec.task.id, arm=spec.arm.name, repeat=spec.repeat,
        attempt=attempt, status="error", started_at=utc_now(), concurrency=concurrency,
        agent_version=agent_version, fingerprint=exp.fingerprint, retries_used=retries_used,
    )  # fmt: skip
    rec.tool_version = __version__
    art: Path | None = None
    ws: Workspace | None = None
    cancelled = False
    live = _LiveDirs(store, spec.id, attempt)
    try:
        art = _fresh_attempt_dir(store, spec.id, attempt)
        rec.artifacts = store.relpath(art)
        _check_cancel(cancel)
        ws = create_workspace(
            spec.task, spec.arm, root=exp.workspace_root, label=f"{spec.id}-a{attempt}"
        )
        live.add(ws.path)
        if keep:
            _write_text(art / "workspace.txt", str(ws.path) + "\n")
        _execute(exp, spec, attempt, rec, art, ws, cancel, live, keep)
    except _Cancelled:
        cancelled = True
    except Exception as e:  # an attempt must never take the run down with it
        if cancel.is_set():
            cancelled = True
        else:
            rec.status, rec.passed = "error", None
            rec.error = _exception_summary(e)
            if art is not None:
                with contextlib.suppress(OSError):
                    _write_text(art / "traceback.txt", traceback.format_exc())
    finally:
        if ws is not None and (cancelled or not keep) and not destroy_workspace(ws):
            _note_leak(art, ws, live)
        live.close()
    rec.finished_at = utc_now()
    if cancelled:
        rec.status, rec.passed, rec.error = "error", None, "cancelled"
        if art is not None:
            _remove_dir(art)
        return rec
    if art is not None:
        try:
            _write_text(art / "record.json", json.dumps(rec.to_dict(), indent=2) + "\n")
        except (OSError, ValueError) as e:
            # The log is the record, so this changes nothing about the outcome.
            if rec.status == "error" and rec.error is None:
                rec.error = f"cannot write record.json: {e}"
    return rec


# --------------------------------------------------------------------------- scheduling


def arm_problem(exp: Experiment, arm: Arm) -> str | None:
    """Why ``arm``'s agent cannot run here (missing executable, unsafe workspace root), or None.

    May raise: callers report exceptions as availability problems.
    """
    adapter = get_adapter(arm.agent.adapter)
    return adapter.check_available(arm.agent) or adapter.check_workspace_root(
        arm.agent, resolve_workspace_root(exp.workspace_root)
    )


def _check_adapters(exp: Experiment) -> None:
    problems: list[str] = []
    seen: set[str] = set()
    for arm in exp.arms:
        name = arm.agent.adapter
        try:
            msg = arm_problem(exp, arm)
        except AgentABError as e:
            msg = str(e)
        except Exception as e:
            msg = f"availability check failed: {_exception_summary(e)}"
        if msg:
            line = f"{name}: {msg}"
            if line not in seen:
                seen.add(line)
                problems.append(f"arm {arm.name!r} uses {line}")
    if problems:
        raise AdapterError("cannot run the experiment:\n  - " + "\n  - ".join(problems))


def _unused_run_dir(base: Path) -> Path:
    # Two runs started within the same second would otherwise collide on the timestamp.
    candidate, n = base, 1
    while candidate.exists():
        n += 1
        candidate = base.with_name(f"{base.name}-{n}")
    return candidate


def run_experiment(
    exp: Experiment,
    run_dir: Path | None = None,
    *,
    resume: bool = False,
    options: RunOptions | None = None,
) -> RunSummary:
    """Run (or resume) every planned trial of ``exp`` and return a summary.

    Fails fast with ``AdapterError`` before creating anything when an agent cannot be launched,
    and with ``RunStoreError`` when the run directory is unusable. ``options.dry_run`` plans
    only: no directories, no processes. A KeyboardInterrupt in the calling thread cancels the
    run: running agents are killed, their attempts are not recorded, and the summary says
    ``cancelled=True``. A run directory takes one session at a time: a second one gets
    ``RunStoreError`` before anything runs, and a crashed one holds nothing (see ``RunLock``).
    """
    options = options or RunOptions()
    lock = RunLock()
    try:
        return _run_experiment(exp, run_dir, resume, options, lock)
    finally:
        lock.release()


def _run_experiment(
    exp: Experiment, run_dir: Path | None, resume: bool, options: RunOptions, lock: RunLock
) -> RunSummary:
    jobs = max(1, options.jobs if options.jobs is not None else exp.jobs)
    budget = options.budget_usd if options.budget_usd is not None else exp.budget_usd
    keep = options.keep_workspaces if options.keep_workspaces is not None else exp.keep_workspaces
    plan = plan_trials(exp)
    total = len(plan)

    def emit(kind: ProgressKind, **kw) -> None:
        if options.progress is None:
            return
        # A broken progress display must not abort paid-for work.
        with contextlib.suppress(Exception):
            options.progress(ProgressEvent(kind, done=done, total=total, spent_usd=spent, **kw))

    # Resolve the run directory and prior state without writing anything yet.
    store: RunStore | None = None
    finals: dict[str, TrialRecord] = {}
    # trial id -> attempts that do not count against max_retries
    retry_base: dict[str, int] = {}
    # arm -> isolation breaches since its last graded trial
    breaches: dict[str, int] = {}
    if resume:
        if run_dir is None:
            raise RunStoreError("resuming needs the run directory to continue")
        store = RunStore.open(Path(run_dir))
        if not options.dry_run:
            lock.acquire(store.run_dir)
            store = RunStore.open(Path(run_dir))  # what the previous session left, now settled
        store.check_compatible(exp, force=options.force)
        recorded = store.records()
        finals = store.final_records()
        retry_base.update(retry_bases(recorded))
        arm_names = {arm.name for arm in exp.arms}
        for prior in recorded:  # across sessions, or each resume would pay for a full streak
            if prior.arm not in arm_names:
                continue
            if prior.isolation_breach:
                breaches[prior.arm] = breaches.get(prior.arm, 0) + 1
            elif prior.status != "error":
                breaches[prior.arm] = 0
        # Records of trials outside the current plan (e.g. arms or tasks filtered out) must
        # not count as progress for this session.
        planned_ids = {spec.id for spec in plan}
        foreign = sorted(tid for tid in finals if tid not in planned_ids)
        for tid in foreign:
            del finals[tid]
        prior_cost = store.total_cost()
    else:
        run_dir = Path(run_dir) if run_dir is not None else _unused_run_dir(default_run_dir(exp))
        check_new_run_dir(run_dir)
        foreign = []
        prior_cost = 0.0
    # Agents run with the workspace as their cwd, so every artifact path handed to them
    # must be absolute or their files land inside the workspace.
    run_dir = Path(run_dir).resolve()

    _check_adapters(exp)

    pending: deque[tuple[TrialSpec, int]] = deque()
    final_status: dict[str, str] = {}  # trial id -> "pass"/"fail"/"error" once done
    for spec in plan:
        rec = finals.get(spec.id)
        if rec is None:
            pending.append((spec, 0))
        elif not is_done(rec, exp.max_retries, retry_base.get(spec.id, 0)):
            pending.append((spec, rec.attempt + 1))
        elif rec.status == "error" and options.retry_errors:
            retry_base[spec.id] = rec.attempt + 1
            pending.append((spec, rec.attempt + 1))
        else:
            final_status[spec.id] = rec.status
    done = len(final_status)
    spent = prior_cost

    isolation_halt: str | None = None
    infra_halt: str | None = None
    open_breaches: set[str] = set()

    def summary(*, cancelled: bool, budget_exhausted: bool, skipped: int) -> RunSummary:
        values = list(final_status.values())
        return RunSummary(
            run_dir=run_dir, planned=total, completed=sum(v != "error" for v in values),
            errors=values.count("error"), skipped_budget=skipped, cancelled=cancelled,
            total_cost_usd=round(spent, 6), budget_exhausted=budget_exhausted,
            isolation_halt=isolation_halt, infra_halt=infra_halt,
            open_breaches=len(open_breaches),
        )  # fmt: skip

    if options.dry_run:
        emit("info", message=f"dry run: {len(pending)} of {total} trials would run, jobs={jobs}")
        return summary(cancelled=False, budget_exhausted=False, skipped=0)

    if store is None:
        run_dir.mkdir(parents=True, exist_ok=True)
        lock.acquire(run_dir)
        store = RunStore.create(run_dir, exp, planned_trials=total)
    elif changes := store.forced_changes(exp):
        store.record_forced_resume(exp, total, changes)
    elif store.meta.get("planned_trials") != total:
        store.update_meta(planned_trials=total)
    _sweep_leftovers(store.run_dir)
    versions = _probe_versions(exp)
    if versions:
        store.update_meta(agent_versions=versions)

    if foreign:
        emit(
            "info",
            message=f"ignoring {len(foreign)} recorded trials that are not in the "
            f"current plan (e.g. {foreign[0]})",
        )
    if done:
        emit("info", message=f"resuming: {done} of {total} trials already done")
    emit("info", message=f"{len(pending)} trials to run, jobs={jobs}")

    cancel = threading.Event()
    running: dict[Future[TrialRecord], tuple[TrialSpec, int]] = {}
    budget_exhausted = cancelled = False
    errors_in_row: dict[str, int] = {}  # arm -> infrastructure errors since its last graded trial
    pool = ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="agent-ab-trial")

    def collect(fut: Future[TrialRecord]) -> None:
        nonlocal done, spent, isolation_halt, infra_halt
        spec, attempt = running.pop(fut)
        try:
            rec = fut.result()
        except BaseException as e:  # run_trial never raises; this guards against bugs in it
            rec = TrialRecord(
                trial_id=spec.id, task=spec.task.id, arm=spec.arm.name, repeat=spec.repeat,
                attempt=attempt, status="error", error=_exception_summary(e),
                started_at=utc_now(), finished_at=utc_now(),
            )  # fmt: skip
        if cancel.is_set() and rec.status == "error":
            return  # interrupted attempts are discarded; ones that finished were paid for
        try:
            store.append(rec)
        except OSError:
            if cancel.is_set():
                return  # shutting down: the other agents still have to be collected
            raise
        spent += rec.cost_usd or 0.0
        arm = spec.arm.name
        if rec.isolation_breach:
            breaches[arm] = breaches.get(arm, 0) + 1
            retry_base[spec.id] = retry_base.get(spec.id, 0) + 1
            open_breaches.add(spec.id)
        elif rec.status != "error":
            breaches[arm] = errors_in_row[arm] = 0
        else:
            errors_in_row[arm] = errors_in_row.get(arm, 0) + 1
            # One trial using all its retries is not an outage.
            limit = max(_MAX_CONSECUTIVE_ERRORS, exp.max_retries + 2)
            if errors_in_row[arm] >= limit and infra_halt is None:
                infra_halt = (
                    f"{errors_in_row[arm]} attempts in a row in arm {arm} ended in an "
                    f"infrastructure error; not starting more trials. Last one: {rec.error}"
                )
                emit("halt", message=infra_halt)
        if rec.isolation_breach:
            emit("finish", trial_id=spec.id, attempt=attempt, record=rec)
            streak = sum(breaches.values())
            if streak >= _MAX_CONSECUTIVE_BREACHES and isolation_halt is None:
                isolation_halt = (
                    f"{streak} isolation breaches with no graded trial since in their arms; not "
                    f"starting more trials. Last one: {rec.error}"
                )
                emit("halt", message=isolation_halt)
            return
        if rec.status == "error" and attempt - retry_base.get(spec.id, 0) < exp.max_retries:
            pending.append((spec, attempt + 1))
            emit(
                "retry",
                trial_id=spec.id,
                attempt=attempt,
                record=rec,
                message=f"retrying after: {rec.error}",
            )
            return
        final_status[spec.id] = rec.status
        done += 1
        emit("finish", trial_id=spec.id, attempt=attempt, record=rec)

    def drain() -> None:
        # Wait in short slices: an unbounded wait would swallow Ctrl-C on Windows.
        while running:
            try:
                finished, _ = wait(list(running), timeout=_WAIT_S, return_when=FIRST_COMPLETED)
                for fut in finished:
                    collect(fut)
            except KeyboardInterrupt:
                cancel.set()

    try:
        while pending or running:
            while (
                pending
                and len(running) < jobs
                and not (budget_exhausted or isolation_halt or infra_halt)
            ):
                if budget is not None and spent >= budget:
                    budget_exhausted = True
                    emit(
                        "budget",
                        message=f"budget ${budget:g} reached (spent ${spent:.2f}); "
                        "not starting more trials",
                    )
                    break
                spec, attempt = pending.popleft()
                emit("start", trial_id=spec.id, attempt=attempt)
                fut = pool.submit(
                    run_trial,
                    exp,
                    spec,
                    attempt,
                    store,
                    cancel,
                    keep_workspaces=keep,
                    concurrency=len(running) + 1,
                    agent_version=versions.get(spec.arm.name),
                    retries_used=attempt - retry_base.get(spec.id, 0),
                )
                running[fut] = (spec, attempt)
            if not running:
                break
            finished, _ = wait(list(running), timeout=_WAIT_S, return_when=FIRST_COMPLETED)
            for fut in finished:
                collect(fut)
    except KeyboardInterrupt:
        cancelled = True
        cancel.set()
        emit("info", message="cancelling: stopping running trials")
    except BaseException:
        cancel.set()
        drain()
        pool.shutdown(wait=True)
        raise
    drain()
    pool.shutdown(wait=True)
    _drop_empty(store.run_dir / IN_USE_DIR)

    skipped = len({spec.id for spec, _ in pending}) if budget_exhausted and not cancelled else 0
    return summary(cancelled=cancelled, budget_exhausted=budget_exhausted, skipped=skipped)
