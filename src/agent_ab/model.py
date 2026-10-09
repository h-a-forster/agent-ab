"""Core data model shared by every agent-ab module.

Everything here is plain data: loading lives in ``config``, execution in ``runner``,
statistics in ``stats``. Keeping the types in one place keeps the modules decoupled.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

SCHEMA_VERSION = 1

# Commands (task setup/check) are either a shell string or an argv list.
# Inside argv lists and shell strings, "{python}" expands to the interpreter running agent-ab.
Command = str | tuple[str, ...]

TrialStatus = Literal["pass", "fail", "error"]


# --------------------------------------------------------------------------- configuration


@dataclass(frozen=True)
class AgentSpec:
    """How to launch one agent. Fully resolved: experiment defaults merged with arm overrides."""

    adapter: str  # "claude-code" | "codex" | "command" | "mock"
    model: str | None = None
    effort: str | None = None
    args: tuple[str, ...] = ()  # extra CLI arguments, appended after adapter-generated ones
    env: dict[str, str] = field(default_factory=dict)  # added to the inherited environment
    command: tuple[str, ...] | None = None  # argv template, "command" adapter only
    options: dict[str, Any] = field(default_factory=dict)  # adapter-specific settings


@dataclass(frozen=True)
class Arm:
    """One configuration under test."""

    name: str
    agent: AgentSpec
    description: str = ""
    overlay: Path | None = None  # directory copied onto the workspace before the agent runs
    remove: tuple[str, ...] = ()  # workspace-relative paths deleted before the overlay is applied
    prompt_prefix: str = ""
    prompt_suffix: str = ""


@dataclass(frozen=True)
class Task:
    """One unit of work with a hidden pass/fail check."""

    id: str  # directory name; [A-Za-z0-9._-]+
    path: Path  # task directory (contains task.toml)
    prompt: str
    check: Command  # exit code 0 = pass; runs in the workspace after `checks/` is copied in
    repo: Path | None = None  # starting files (task_dir/repo), copied into the workspace
    checks: Path | None = None  # hidden files (task_dir/checks), copied in only for the check
    solution: Path | None = None  # reference solution overlay (task_dir/solution), optional
    setup: Command | None = None  # runs in the workspace before the agent; failure = infra error
    timeout_s: float | None = None  # overrides the experiment's agent timeout
    check_timeout_s: float | None = None  # overrides the experiment's check timeout
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Experiment:
    name: str
    config_path: Path
    root: Path  # directory containing the config file; relative paths resolve against it
    tasks: tuple[Task, ...]
    arms: tuple[Arm, ...]
    baseline: str  # arm name every other arm is compared against
    repeats: int = 1
    jobs: int = 1
    seed: int = 0
    budget_usd: float | None = None
    timeout_s: float = 1800.0
    check_timeout_s: float = 600.0
    max_retries: int = 2  # extra attempts after an infrastructure error
    timeout_is_failure: bool = True  # agent timeout => fail, without running the check
    keep_workspaces: bool = False
    workspace_root: Path | None = None  # default: the system temp directory
    fingerprint: str = ""  # sha256 over resolved config + task/overlay file contents
    description: str = ""

    def arm(self, name: str) -> Arm:
        for a in self.arms:
            if a.name == name:
                return a
        raise KeyError(name)

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)


# --------------------------------------------------------------------------- execution


def trial_id(task_id: str, arm_name: str, repeat: int) -> str:
    """Stable, filesystem-safe identifier for one (task, arm, repeat) cell."""
    return f"{task_id}__{arm_name}__r{repeat}"


def trial_seed(experiment_seed: int, tid: str) -> int:
    """Deterministic per-trial seed derived from the experiment seed and trial id."""
    digest = hashlib.sha256(f"{experiment_seed}:{tid}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True)
class TrialSpec:
    task: Task
    arm: Arm
    repeat: int  # 0-based

    @property
    def id(self) -> str:
        return trial_id(self.task.id, self.arm.name, self.repeat)


@dataclass(frozen=True)
class ProcResult:
    """Outcome of one subprocess run (see ``proc.run_process``)."""

    exit_code: int | None  # None when the process could not start or was killed on timeout
    timed_out: bool
    duration_s: float
    stdout_path: Path
    stderr_path: Path
    start_error: str | None = None  # set when the executable could not be launched


@dataclass
class TrialContext:
    """Everything an adapter needs to build an invocation for one attempt."""

    spec: AgentSpec
    task: Task
    arm: Arm
    repeat: int
    attempt: int
    prompt: str
    workspace: Path
    artifacts: Path  # per-attempt directory for logs, transcripts, usage files
    seed: int
    root: Path | None = None  # experiment directory, for wrapper scripts shipped beside the config


@dataclass
class AgentInvocation:
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)  # additions to the inherited environment
    stdin: str | None = None
    cwd: Path | None = None  # default: the workspace


@dataclass
class AgentUsage:
    """What an adapter could extract from the agent's output. Unknown values stay None."""

    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    turns: int | None = None
    final_message: str | None = None
    # Set when the run failed for reasons unrelated to the configuration under test
    # (authentication, rate limiting, provider outage). The attempt is retried and,
    # if it never succeeds, excluded from statistics.
    infra_error: str | None = None


@dataclass
class TrialRecord:
    """One line of ``trials.jsonl``. Every attempt is recorded; the last attempt per trial wins."""

    trial_id: str
    task: str
    arm: str
    repeat: int
    attempt: int
    status: TrialStatus  # "error" = infrastructure failure, excluded from statistics
    passed: bool | None = None
    agent_exit_code: int | None = None
    agent_timed_out: bool = False
    check_exit_code: int | None = None
    check_timed_out: bool = False
    duration_s: float | None = None  # agent wall-clock time
    check_duration_s: float | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    turns: int | None = None
    files_changed: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    error: str | None = None
    started_at: str | None = None  # ISO-8601 UTC
    finished_at: str | None = None
    artifacts: str | None = None  # run-dir-relative path, forward slashes
    schema: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrialRecord:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------- analysis


@dataclass
class Interval:
    estimate: float | None
    low: float | None
    high: float | None


@dataclass
class ArmSummary:
    arm: str
    trials: int  # completed trials (pass + fail)
    errors: int  # trials whose final attempt was an infrastructure error
    passes: int
    tasks: int  # tasks with at least one completed trial
    pass_rate: Interval  # task-macro mean; CI from a cluster bootstrap over tasks
    pass_rate_wilson: Interval  # trial-level Wilson interval (ignores task clustering)
    mean_cost_usd: Interval  # per trial; None when no trial reported cost
    total_cost_usd: float | None
    mean_duration_s: Interval
    mean_input_tokens: float | None
    mean_output_tokens: float | None
    mean_turns: float | None
    cost_per_pass_usd: float | None  # total cost / passes


@dataclass
class Comparison:
    """Arm versus the baseline, paired over tasks both arms completed."""

    arm: str
    baseline: str
    paired_tasks: int
    pass_rate_diff: Interval  # arm - baseline, in absolute rate (0.10 = +10 points)
    p_value: float | None  # two-sided paired sign-flip permutation test over tasks
    p_value_adjusted: float | None  # Holm-adjusted across all comparisons in the report
    cost_ratio: Interval  # mean cost arm / mean cost baseline
    duration_ratio: Interval
    tasks_better: int  # tasks where the arm's pass fraction is higher
    tasks_worse: int
    tasks_tied: int
    verdict: Literal["better", "worse", "no detectable difference", "insufficient data"]


@dataclass
class TaskCell:
    task: str
    arm: str
    trials: int
    passes: int
    errors: int
    mean_cost_usd: float | None
    mean_duration_s: float | None


@dataclass
class Analysis:
    experiment: str
    baseline: str
    alpha: float
    arms: list[ArmSummary]
    comparisons: list[Comparison]
    cells: list[TaskCell]  # one per (task, arm)
    flaky_tasks: list[str]  # tasks whose outcome varied across repeats within some arm
    planned_trials: int
    completed_trials: int
    error_trials: int
    total_cost_usd: float | None
    notes: list[str] = field(default_factory=list)  # human-readable caveats for the report
