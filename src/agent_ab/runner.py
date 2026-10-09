"""Execute an experiment: plan trials, run them concurrently, retry, budget, resume, cancel.

Every attempt runs in a fresh workspace and is appended to the run store as soon as it
finishes, so the log on disk is always the complete truth. Infrastructure errors are retried;
a budget stops new launches; Ctrl-C kills running agents and records nothing half-done.
"""

from __future__ import annotations

import contextlib
import json
import math
import random
import threading
import traceback
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agent_ab.adapters import get_adapter
from agent_ab.adapters.base import Adapter
from agent_ab.errors import AdapterError, AgentABError, RunStoreError
from agent_ab.model import (
    AgentUsage,
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
    MAX_COST_USD,
    TRIALS_DIR,
    RunStore,
    check_new_run_dir,
    is_done,
    utc_now,
)
from agent_ab.workspace import (
    Workspace,
    create_workspace,
    destroy_workspace,
    diff_stats,
    install_checks,
    rebaseline,
    run_command,
)

_WAIT_S = 0.2  # main-thread wait slice; short so Ctrl-C is delivered promptly on Windows

ProgressKind = Literal["start", "finish", "retry", "budget", "info"]


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
    progress: Callable[[ProgressEvent], None] | None = field(default=None, repr=False)


@dataclass
class RunSummary:
    """Outcome of ``run_experiment``. Counts cover the whole run, earlier sessions included."""

    run_dir: Path
    planned: int
    completed: int  # trials whose final attempt passed or failed
    errors: int  # trials whose retries are exhausted with an infrastructure error
    skipped_budget: int  # trials left unfinished because the budget ran out
    cancelled: bool
    total_cost_usd: float
    budget_exhausted: bool


class _Cancelled(Exception):
    """Internal: the attempt was interrupted and must not be recorded."""


# --------------------------------------------------------------------------- planning


def plan_trials(exp: Experiment) -> list[TrialSpec]:
    """Every (task, arm, repeat) cell, shuffled deterministically by the experiment seed.

    Shuffling spreads arms over time so drift (provider load, rate limits, caches) does not
    line up with one arm.
    """
    plan = [
        TrialSpec(task=task, arm=arm, repeat=r)
        for task in exp.tasks
        for arm in exp.arms
        for r in range(exp.repeats)
    ]
    random.Random(exp.seed).shuffle(plan)
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


def _note_leak(art: Path | None, ws: Workspace) -> None:
    # Something still holds files in the workspace; leave a pointer so it can be cleaned up.
    if art is not None and art.is_dir():
        with contextlib.suppress(OSError):
            _write_text(art / "workspace-leaked.txt", str(ws.path) + "\n")


def _remove_dir(path: Path) -> None:
    destroy_workspace(Workspace(path=path))  # robust, retrying, never raises


def _fresh_attempt_dir(store: RunStore, tid: str, attempt: int) -> Path:
    # A crash or Ctrl-C in an earlier session may have left an unrecorded attempt folder
    # behind; its files must not be mistaken for this attempt's.
    stale = store.run_dir / TRIALS_DIR / tid / f"attempt-{attempt}"
    if stale.exists():
        _remove_dir(stale)
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
    for name in _USAGE_COUNTS:
        raw = getattr(usage, name)
        value = _sane_count(raw)
        if value is None and raw is not None:
            dropped.append(f"{name}: {_short_repr(raw)}")
        setattr(rec, name, value)
    return dropped


def _write_usage_warning(art: Path, notes: list[str]) -> None:
    with (
        contextlib.suppress(OSError),
        open(art / "usage_warning.txt", "a", encoding="utf-8", newline="\n") as f,
    ):
        f.write("".join(n + "\n" for n in notes))


def _parse_usage(adapter: Adapter, ctx: TrialContext, result: ProcResult, art: Path) -> AgentUsage:
    """Run the adapter's parser, treating any failure as "usage unknown".

    The agent did run, so a parser crash on hostile or unexpected output must not turn the
    attempt into an infrastructure error (which would be retried and excluded).
    """
    try:
        usage = adapter.parse(ctx, result)
    except Exception as e:
        _write_usage_warning(art, [f"usage could not be parsed: {_exception_summary(e)}"])
        return AgentUsage()
    if not isinstance(usage, AgentUsage):
        _write_usage_warning(art, [f"adapter returned {type(usage).__name__}; usage ignored"])
        return AgentUsage()
    return usage


def _execute(
    exp: Experiment,
    spec: TrialSpec,
    attempt: int,
    rec: TrialRecord,
    art: Path,
    ws: Workspace,
    cancel: threading.Event,
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
    result = run_process(
        inv.argv,
        cwd=inv.cwd or ws.path,
        env=build_env({**arm.agent.env, **inv.env}),
        timeout_s=agent_timeout,
        stdout_path=art / "agent.stdout",
        stderr_path=art / "agent.stderr",
        stdin_text=inv.stdin,
        cancel=cancel,
    )
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
    if usage.infra_error:
        rec.error = f"infrastructure error: {usage.infra_error}"
        return

    try:
        _grade(exp, rec, art, ws, task, result, agent_timeout, check_timeout, cancel)
    except _Cancelled:
        raise
    except Exception as e:
        if cancel.is_set():
            raise _Cancelled from e
        # The agent ran; whatever it did to the workspace that breaks grading (deleted .git,
        # links over check paths, unreadable files) is its outcome, not an infrastructure
        # problem. Retrying would bill again and excluding would hide sabotage.
        rec.status, rec.passed = "fail", False
        rec.error = f"grading failed after the agent ran: {_exception_summary(e)}"
        with contextlib.suppress(OSError):
            _write_text(art / "traceback.txt", traceback.format_exc())


def _grade(
    exp: Experiment,
    rec: TrialRecord,
    art: Path,
    ws: Workspace,
    task: Task,
    result: ProcResult,
    agent_timeout: float,
    check_timeout: float,
    cancel: threading.Event,
) -> None:
    """Diff, install the hidden checks and run them. Fills ``rec`` in place."""
    # Measured before the checks are copied in so they never count as agent changes.
    stats = diff_stats(ws, art / "diff.patch")
    if stats is not None:
        rec.files_changed, rec.lines_added, rec.lines_removed = stats

    if result.timed_out and exp.timeout_is_failure:
        rec.status, rec.passed = "fail", False
        rec.error = f"agent timed out after {agent_timeout:g}s"
        return

    install_checks(ws, task)
    check = run_command(
        task.check, ws, timeout_s=check_timeout,
        stdout_path=art / "check.stdout", stderr_path=art / "check.stderr", cancel=cancel,
    )  # fmt: skip
    _check_cancel(cancel, check)
    rec.check_exit_code = check.exit_code
    rec.check_timed_out = check.timed_out
    rec.check_duration_s = round(check.duration_s, 3)
    if check.start_error:
        # Also how an agent that deleted the workspace ends up; a broken check command is
        # caught by `validate --tasks` before anything is spent.
        rec.status, rec.passed = "fail", False
        rec.error = f"check could not start: {check.start_error}"
        return
    if check.timed_out:
        rec.status, rec.passed = "fail", False
        rec.error = f"check timed out after {check_timeout:g}s"
        return
    rec.status = "pass" if check.exit_code == 0 else "fail"
    rec.passed = rec.status == "pass"


def run_trial(
    exp: Experiment,
    spec: TrialSpec,
    attempt: int,
    store: RunStore,
    cancel: threading.Event,
    *,
    keep_workspaces: bool | None = None,
) -> TrialRecord:
    """Run one attempt of one trial and return its record. Never raises.

    The record is written to ``record.json`` in the attempt folder but not appended to the
    log; the scheduler does that. If ``cancel`` is set mid-attempt the attempt folder is
    removed and the returned record has status ``error`` and error ``"cancelled"``; such a
    record must not be stored. ``keep_workspaces`` defaults to the experiment's setting.
    """
    keep = exp.keep_workspaces if keep_workspaces is None else keep_workspaces
    rec = TrialRecord(
        trial_id=spec.id, task=spec.task.id, arm=spec.arm.name, repeat=spec.repeat,
        attempt=attempt, status="error", started_at=utc_now(),
    )  # fmt: skip
    art: Path | None = None
    ws: Workspace | None = None
    cancelled = False
    try:
        art = _fresh_attempt_dir(store, spec.id, attempt)
        rec.artifacts = store.relpath(art)
        _check_cancel(cancel)
        ws = create_workspace(
            spec.task, spec.arm, root=exp.workspace_root, label=f"{spec.id}-a{attempt}"
        )
        if keep:
            _write_text(art / "workspace.txt", str(ws.path) + "\n")
        _execute(exp, spec, attempt, rec, art, ws, cancel)
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
            _note_leak(art, ws)
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
            if rec.error is None:
                rec.error = f"cannot write record.json: {e}"
    return rec


# --------------------------------------------------------------------------- scheduling


def _check_adapters(exp: Experiment) -> None:
    problems: list[str] = []
    seen: set[str] = set()
    for arm in exp.arms:
        name = arm.agent.adapter
        try:
            msg = get_adapter(name).check_available(arm.agent)
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
    ``cancelled=True``.
    """
    options = options or RunOptions()
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
    if resume:
        if run_dir is None:
            raise RunStoreError("resuming needs the run directory to continue")
        store = RunStore.open(Path(run_dir))
        store.check_compatible(exp, force=options.force)
        finals = store.final_records()
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
        elif is_done(rec, exp.max_retries):
            final_status[spec.id] = rec.status
        else:
            pending.append((spec, rec.attempt + 1))
    done = len(final_status)
    spent = prior_cost

    def summary(*, cancelled: bool, budget_exhausted: bool, skipped: int) -> RunSummary:
        values = list(final_status.values())
        return RunSummary(
            run_dir=run_dir, planned=total, completed=sum(v != "error" for v in values),
            errors=values.count("error"), skipped_budget=skipped, cancelled=cancelled,
            total_cost_usd=round(spent, 6), budget_exhausted=budget_exhausted,
        )  # fmt: skip

    if options.dry_run:
        emit("info", message=f"dry run: {len(pending)} of {total} trials would run, jobs={jobs}")
        return summary(cancelled=False, budget_exhausted=False, skipped=0)

    if store is None:
        store = RunStore.create(run_dir, exp, planned_trials=total)
    elif store.meta.get("planned_trials") != total:
        store.update_meta(planned_trials=total)

    if foreign:
        emit("info", message=f"ignoring {len(foreign)} recorded trials that are not in the "
             f"current plan (e.g. {foreign[0]})")
    if done:
        emit("info", message=f"resuming: {done} of {total} trials already done")
    emit("info", message=f"{len(pending)} trials to run, jobs={jobs}")

    cancel = threading.Event()
    running: dict[Future[TrialRecord], tuple[TrialSpec, int]] = {}
    budget_exhausted = cancelled = False
    pool = ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="agent-ab-trial")

    def collect(fut: Future[TrialRecord]) -> None:
        nonlocal done, spent
        spec, attempt = running.pop(fut)
        try:
            rec = fut.result()
        except BaseException as e:  # run_trial never raises; this guards against bugs in it
            rec = TrialRecord(
                trial_id=spec.id, task=spec.task.id, arm=spec.arm.name, repeat=spec.repeat,
                attempt=attempt, status="error", error=_exception_summary(e),
                started_at=utc_now(), finished_at=utc_now(),
            )  # fmt: skip
        if cancel.is_set():
            return  # interrupted attempts are discarded, not recorded
        store.append(rec)
        spent += rec.cost_usd or 0.0
        if rec.status == "error" and attempt < exp.max_retries:
            pending.append((spec, attempt + 1))
            emit("retry", trial_id=spec.id, attempt=attempt, record=rec,
                 message=f"retrying after: {rec.error}")
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
            while pending and len(running) < jobs and not budget_exhausted:
                if budget is not None and spent >= budget:
                    budget_exhausted = True
                    emit("budget", message=f"budget ${budget:g} reached (spent ${spent:.2f}); "
                         "not starting more trials")
                    break
                spec, attempt = pending.popleft()
                emit("start", trial_id=spec.id, attempt=attempt)
                fut = pool.submit(run_trial, exp, spec, attempt, store, cancel,
                                  keep_workspaces=keep)
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

    skipped = len({spec.id for spec, _ in pending}) if budget_exhausted and not cancelled else 0
    return summary(cancelled=cancelled, budget_exhausted=budget_exhausted, skipped=skipped)
