import errno
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agent_ab import adapters
from agent_ab.adapters.base import Adapter
from agent_ab.adapters.claude_code import ClaudeCodeAdapter
from agent_ab.config import compute_fingerprint
from agent_ab.errors import AdapterError, RunStoreError
from agent_ab.model import (
    AgentInvocation,
    AgentSpec,
    AgentUsage,
    Arm,
    Experiment,
    ProcResult,
    Task,
    TrialContext,
    TrialRecord,
    TrialSpec,
)
from agent_ab.runner import (
    RunOptions,
    default_run_dir,
    plan_trials,
    run_experiment,
    run_trial,
)
from agent_ab.stats import analyze
from agent_ab.store import TRIALS_FILE, RunStore

PY = sys.executable
HAS_GIT = shutil.which("git") is not None

# Agent snippets. Each runs with cwd = workspace; FAKE_ATTEMPT / FAKE_ARTIFACTS are set.
SOLVE = "open('solution.txt', 'w').write('ok')"
NOTHING = "pass"
CRASH = "import sys; sys.exit(3)"
HANG = "import time; time.sleep(30)"
CHECK_SOLVED = (PY, "-c", "import os, sys; sys.exit(0 if os.path.exists('solution.txt') else 1)")


def usage_snippet(**usage) -> str:
    return (
        "import json, os; open(os.path.join(os.environ['FAKE_ARTIFACTS'], 'usage.json'), 'w')"
        f".write(json.dumps({usage!r}))"
    )


class FakeAdapter(Adapter):
    """Runs ``options['script']`` with the interpreter; reads optional usage.json."""

    name = "fake"
    option_keys = frozenset(
        {
            "script",
            "missing",
            "build_error",
            "argv",
            "parse_error",
            "version",
            "version_error",
            "isolate",
        }
    )

    def check_available(self, spec: AgentSpec) -> str | None:
        return spec.options.get("missing")

    def version(self, spec: AgentSpec) -> str | None:
        if spec.options.get("version_error"):
            raise RuntimeError("boom in version")
        return spec.options.get("version")

    def build(self, ctx: TrialContext) -> AgentInvocation:
        if ctx.spec.options.get("build_error"):
            raise RuntimeError("boom in build")
        argv = ctx.spec.options.get("argv") or [PY, "-c", ctx.spec.options.get("script", "")]
        env = {"FAKE_ATTEMPT": str(ctx.attempt), "FAKE_ARTIFACTS": str(ctx.artifacts)}
        if not ctx.spec.options.get("isolate"):
            return AgentInvocation(argv=list(argv), env=env)
        temp = ctx.workspace.with_name(ctx.workspace.name + ".private")
        temp.mkdir()
        base = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT")}
        env["FAKE_TEMP"] = str(temp)
        return AgentInvocation(
            argv=list(argv), env=env, base_env={**base, "BASE_ONLY": "1"}, temp_dirs=[temp]
        )

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        if ctx.spec.options.get("parse_error"):
            raise RecursionError("maximum recursion depth exceeded")
        path = ctx.artifacts / "usage.json"
        if not path.exists():
            return AgentUsage()
        return AgentUsage(**json.loads(path.read_text(encoding="utf-8")))


@pytest.fixture(autouse=True)
def fake_adapter(monkeypatch):
    monkeypatch.setitem(adapters._REGISTRY, "fake", "unused:Unused")
    monkeypatch.setitem(adapters._INSTANCES, "fake", FakeAdapter())


def make_task(tmp_path: Path, tid: str = "t1", **kw) -> Task:
    task_dir = tmp_path / "tasks" / tid
    repo = task_dir / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    fields = {
        "id": tid,
        "path": task_dir,
        "prompt": "Write solution.txt.",
        "check": CHECK_SOLVED,
        "repo": repo,
    }
    fields.update(kw)
    return Task(**fields)


def fake_arm(name: str, script: str = SOLVE, **kw) -> Arm:
    options = kw.pop("options", {})
    return Arm(
        name=name, agent=AgentSpec(adapter="fake", options={"script": script, **options}), **kw
    )


def make_exp(tmp_path: Path, arms=None, tasks=None, **kw) -> Experiment:
    arms = tuple(arms or (fake_arm("a"), fake_arm("b")))
    tasks = tuple(tasks or (make_task(tmp_path),))
    fields = {
        "repeats": 1,
        "jobs": 1,
        "max_retries": 2,
        "timeout_s": 60.0,
        "check_timeout_s": 60.0,
        "workspace_root": tmp_path / "ws",
    }
    fields.update(kw)
    exp = Experiment(
        name="exp",
        config_path=tmp_path / "experiment.toml",
        root=tmp_path,
        tasks=tasks,
        arms=arms,
        baseline=arms[0].name,
        **fields,
    )
    return replace(exp, fingerprint=compute_fingerprint(exp))


def records(run_dir: Path) -> list[TrialRecord]:
    return RunStore.open(run_dir).records()


def ws_left(tmp_path: Path) -> list[Path]:
    root = tmp_path / "ws"
    return list(root.iterdir()) if root.exists() else []


def run_one(tmp_path: Path, script: str, **kw) -> TrialRecord:
    """Run a single-arm, single-task experiment and return the only final record."""
    task_kw = kw.pop("task_kw", {})
    exp = make_exp(
        tmp_path, arms=[fake_arm("a", script)], tasks=[make_task(tmp_path, **task_kw)], **kw
    )
    summary = run_experiment(exp, tmp_path / "run")
    assert summary.planned == 1
    final = RunStore.open(tmp_path / "run").final_records()
    assert ws_left(tmp_path) == []
    return final["t1__a__r0"]


# --------------------------------------------------------------------------- planning


def test_plan_is_complete_and_deterministic(tmp_path):
    exp = make_exp(
        tmp_path, tasks=[make_task(tmp_path, "t1"), make_task(tmp_path, "t2")], repeats=3, seed=7
    )
    ids = [s.id for s in plan_trials(exp)]
    assert len(ids) == len(set(ids)) == 12
    assert ids == [s.id for s in plan_trials(exp)]
    assert ids != [s.id for s in plan_trials(replace(exp, seed=8))]


def test_plan_keeps_arms_adjacent_in_randomised_order(tmp_path):
    arms = [fake_arm(n) for n in "abc"]
    tasks = [make_task(tmp_path, f"t{i}") for i in range(4)]
    exp = make_exp(tmp_path, arms=arms, tasks=tasks, repeats=2, seed=3)
    plan = plan_trials(exp)
    blocks = [plan[i : i + 3] for i in range(0, len(plan), 3)]
    keys = [(b[0].task.id, b[0].repeat) for b in blocks]
    assert len(set(keys)) == 8
    for b in blocks:
        assert {(s.task.id, s.repeat) for s in b} == {(b[0].task.id, b[0].repeat)}
        assert sorted(s.arm.name for s in b) == ["a", "b", "c"]
    # The arm order varies between blocks, and so does the block order across seeds.
    assert len({tuple(s.arm.name for s in b) for b in blocks}) > 1
    other = [(s.task.id, s.repeat) for s in plan_trials(replace(exp, seed=4))][::3]
    assert other != keys


def test_concurrency_recorded(tmp_path):
    tasks = [make_task(tmp_path, f"t{i}") for i in range(3)]
    exp = make_exp(tmp_path, tasks=tasks, jobs=2)
    run_experiment(exp, tmp_path / "run")
    recs = records(tmp_path / "run")
    assert recs and all(r.concurrency in (1, 2) for r in recs)
    # The log is in finish order, so the first-started trial need not come first.
    assert min(r.concurrency for r in recs) == 1


def test_old_records_without_concurrency_load():
    rec = TrialRecord.from_dict(
        {"trial_id": "t__a__r0", "task": "t", "arm": "a", "repeat": 0, "attempt": 0,
         "status": "pass"}
    )  # fmt: skip
    assert rec.concurrency is None


def test_identity_fields_recorded(tmp_path):
    init = {"model": "claude-x", "tools": ["Bash"], "mcp_servers": []}
    usage = usage_snippet(
        models=["m2", "m1", "m1"], agent_version="9.9.9", agent_init=init, cost_usd=0.1
    )
    arms = (
        fake_arm("a", SOLVE + "\n" + usage, options={"version": "1.2.3"}),
        fake_arm("b", SOLVE, options={"version": " 4.5.6 "}),
        fake_arm("c", SOLVE, options={"version_error": True}),
    )
    run_experiment(make_exp(tmp_path, arms=arms), tmp_path / "run")
    store = RunStore.open(tmp_path / "run")
    # Versions are probed once per arm; an arm whose probe fails is simply absent.
    assert store.meta["agent_versions"] == {"a": "1.2.3", "b": "4.5.6"}
    by_arm = {r.arm: r for r in store.records()}
    a, b, c = by_arm["a"], by_arm["b"], by_arm["c"]
    assert a.models == ["m1", "m2"] and a.agent_init == init
    assert a.agent_version == "9.9.9"  # reported by the agent itself wins over the probe
    assert (b.models, b.agent_init, b.agent_version) == (None, None, "4.5.6")
    assert (c.models, c.agent_version) == (None, None)
    # Round trip through the log and record.json.
    again = TrialRecord.from_dict(json.loads(json.dumps(a.to_dict())))
    assert again == a


def test_malformed_identity_fields_are_dropped(tmp_path):
    usage = usage_snippet(models="claude", agent_version=3, agent_init=["x"])
    arm = fake_arm("a", SOLVE + "\n" + usage)
    run_experiment(make_exp(tmp_path, arms=(arm,)), tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert (rec.models, rec.agent_version, rec.agent_init) == (None, None, None)
    assert "agent_versions" not in RunStore.open(tmp_path / "run").meta


def test_old_records_without_identity_fields_load():
    rec = TrialRecord.from_dict(
        {"trial_id": "t__a__r0", "task": "t", "arm": "a", "repeat": 0, "attempt": 0,
         "status": "pass"}
    )  # fmt: skip
    assert (rec.models, rec.agent_version, rec.agent_init) == (None, None, None)


def test_default_run_dir(tmp_path):
    d = default_run_dir(make_exp(tmp_path))
    assert d.parent == tmp_path / "runs"
    assert d.name.startswith("exp-") and len(d.name) == len("exp-YYYYmmdd-HHMMSS")


# --------------------------------------------------------------------------- status paths


def test_pass_and_artifacts(tmp_path):
    rec = run_one(tmp_path, SOLVE + "\n" + usage_snippet(cost_usd=0.25, input_tokens=10, turns=2))
    assert rec.status == "pass" and rec.passed is True
    assert rec.agent_exit_code == 0 and rec.check_exit_code == 0
    assert rec.cost_usd == 0.25 and rec.input_tokens == 10 and rec.turns == 2
    assert rec.started_at.endswith("Z") and rec.finished_at.endswith("Z")
    assert rec.artifacts == "trials/t1__a__r0/attempt-0"
    art = tmp_path / "run" / rec.artifacts
    for name in (
        "prompt.md",
        "agent.stdout",
        "agent.stderr",
        "check.stdout",
        "check.stderr",
        "record.json",
    ):
        assert (art / name).is_file(), name
    assert not (art / "workspace.txt").exists()
    assert (art / "prompt.md").read_text(encoding="utf-8") == "Write solution.txt.\n"
    assert json.loads((art / "record.json").read_text(encoding="utf-8")) == rec.to_dict()
    if HAS_GIT:
        assert rec.files_changed == 1 and rec.lines_added == 1
        assert "solution.txt" in (art / "diff.patch").read_text(encoding="utf-8")


def test_fail(tmp_path):
    rec = run_one(tmp_path, NOTHING)
    assert rec.status == "fail" and rec.passed is False and rec.check_exit_code == 1
    assert rec.attempt == 0 and rec.error is None


def test_crash_still_checks(tmp_path):
    rec = run_one(tmp_path, CRASH)
    assert rec.status == "fail" and rec.agent_exit_code == 3 and rec.check_exit_code == 1


def test_agent_timeout_is_failure_without_check(tmp_path):
    rec = run_one(tmp_path, HANG, timeout_s=1.0)
    assert rec.status == "fail" and rec.agent_timed_out
    assert rec.check_exit_code is None and "timed out" in rec.error
    assert not (tmp_path / "run" / rec.artifacts / "check.stdout").exists()


def test_agent_timeout_checked_when_not_failure(tmp_path):
    script = SOLVE + "\nimport time; time.sleep(30)"
    rec = run_one(tmp_path, script, timeout_s=6.0, timeout_is_failure=False)
    assert rec.agent_timed_out and rec.status == "pass"


def test_check_timeout_is_fail(tmp_path):
    check = (PY, "-c", "import time; time.sleep(30)")
    rec = run_one(tmp_path, SOLVE, check_timeout_s=1.0, task_kw={"check": check})
    assert rec.status == "fail" and rec.check_timed_out and rec.check_exit_code is None


def test_setup_failure_is_error_and_retried(tmp_path):
    setup = (PY, "-c", "import sys; sys.exit(2)")
    rec = run_one(tmp_path, SOLVE, max_retries=1, task_kw={"setup": setup})
    assert rec.status == "error" and rec.attempt == 1 and "setup" in rec.error
    assert (tmp_path / "run" / rec.artifacts / "setup.stderr").is_file()


def test_setup_runs_before_agent(tmp_path):
    setup = (PY, "-c", "open('prepared.txt', 'w').write('x')")
    script = f"import os\nif os.path.exists('prepared.txt'):\n    {SOLVE}\n"
    rec = run_one(tmp_path, script, task_kw={"setup": setup})
    assert rec.status == "pass"


def test_start_error_is_error_without_check(tmp_path):
    exp = make_exp(
        tmp_path,
        max_retries=0,
        arms=[fake_arm("a", options={"argv": ["no-such-agent-binary-xyz"]})],
    )
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "error" and "could not start" in rec.error
    assert rec.check_exit_code is None


def test_infra_error_retried_then_success(tmp_path):
    script = (
        "import os\n"
        "if os.environ['FAKE_ATTEMPT'] == '0':\n"
        f"    {usage_snippet(cost_usd=0.5, infra_error='rate limited')}\n"
        "else:\n"
        f"    {SOLVE}\n"
    )
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)])
    events = []
    summary = run_experiment(exp, tmp_path / "run", options=RunOptions(progress=events.append))
    recs = records(tmp_path / "run")
    assert [(r.attempt, r.status) for r in recs] == [(0, "error"), (1, "pass")]
    assert recs[0].error == "infrastructure error: rate limited" and recs[0].cost_usd == 0.5
    assert recs[0].check_exit_code is None
    assert summary.completed == 1 and summary.errors == 0 and summary.total_cost_usd == 0.5
    assert [e.kind for e in events if e.kind != "info"] == ["start", "retry", "start", "finish"]
    assert events[-1].done == 1 and events[-1].total == 1 and events[-1].spent_usd == 0.5


def test_infra_error_exhausts_retries(tmp_path):
    exp = make_exp(tmp_path, max_retries=2, arms=[fake_arm("a", usage_snippet(infra_error="down"))])
    summary = run_experiment(exp, tmp_path / "run")
    assert [r.attempt for r in records(tmp_path / "run")] == [0, 1, 2]
    assert summary.errors == 1 and summary.completed == 0


def test_unexpected_exception_is_error(tmp_path):
    exp = make_exp(tmp_path, max_retries=0, arms=[fake_arm("a", options={"build_error": True})])
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "error" and "RuntimeError: boom in build" in rec.error
    assert (tmp_path / "run" / rec.artifacts / "traceback.txt").is_file()
    assert ws_left(tmp_path) == []


# --------------------------------------------------------------------------- isolation breach


class LeakyClaude(ClaudeCodeAdapter):
    """The real adapter and parser, with a Python script in place of the ``claude`` binary."""

    def __init__(self, script: str):
        self.script = script

    def check_workspace_root(self, spec, root):
        return None  # the temp directory may sit under a home directory with its own CLAUDE.md

    def _argv(self, spec, exe, system_prompt_file):
        return [PY, "-c", self.script]


def leaky_agent(counter: Path, leaks: str) -> str:
    """A stream-json agent charging $0.10 that reports user memory when ``leaks`` is true.

    ``n`` is how many agents started before this one.
    """
    memory = str(Path.home() / ".claude" / "projects" / "x" / "memory")
    return (
        "import json, os, pathlib\n"
        f"counter = pathlib.Path({str(counter)!r})\n"
        "n = len(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text('x' * (n + 1))\n"
        f"paths = {{'auto': {memory!r}}} if ({leaks}) else {{}}\n"
        "print(json.dumps({'type': 'system', 'subtype': 'init', 'memory_paths': paths}))\n"
        f"{SOLVE}\n"
        "print(json.dumps({'type': 'result', 'subtype': 'success', 'total_cost_usd': 0.1}))\n"
    )


def leaky_exp(tmp_path, monkeypatch, script: str, *, arms=2, tasks=3, **kw) -> Experiment:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(adapters._REGISTRY, "leaky", "unused:Unused")
    monkeypatch.setitem(adapters._INSTANCES, "leaky", LeakyClaude(script))
    agent = AgentSpec(adapter="leaky", options={"executable": PY})
    tasks = [make_task(tmp_path, f"t{i}") for i in range(tasks)]
    arm_list = [Arm(name=n, agent=agent) for n in "ab"[:arms]]
    return make_exp(tmp_path, arms=arm_list, tasks=tasks, **kw)


@pytest.mark.parametrize("jobs", [1, 2])
def test_repeated_isolation_breach_halts_the_run(tmp_path, monkeypatch, jobs):
    exp = leaky_exp(tmp_path, monkeypatch, leaky_agent(tmp_path / "n", "True"), jobs=jobs)
    summary = run_experiment(exp, tmp_path / "run")
    recs = records(tmp_path / "run")
    assert 3 <= len(recs) <= 2 + jobs  # one more per agent already running when it stops
    assert {r.attempt for r in recs} == {0}  # a breach is not retried
    assert len({r.trial_id for r in recs}) == len(recs)
    assert all(r.status == "error" and "isolation breach" in r.error for r in recs)
    assert all(r.agent_init["config_leaks"] == ["memory_paths.auto: ~/.../memory"] for r in recs)
    assert summary.isolation_halt and "isolation breach" in summary.isolation_halt
    assert summary.total_cost_usd == pytest.approx(0.1 * len(recs))


def test_clean_trial_in_the_arm_between_breaches_does_not_halt(tmp_path, monkeypatch):
    # Breach, breach, clean, repeated in one arm: never three open. A breach is not retried.
    exp = leaky_exp(
        tmp_path, monkeypatch, leaky_agent(tmp_path / "n", "n % 3 != 2"), arms=1, tasks=6
    )
    summary = run_experiment(exp, tmp_path / "run")
    assert summary.isolation_halt is None
    assert len(records(tmp_path / "run")) == 6
    # Breached trials are not finished: they count neither as completed nor as errors.
    assert (summary.completed, summary.errors, summary.open_breaches) == (2, 0, 4)


def test_breaches_in_one_arm_halt_despite_clean_trials_in_the_other(tmp_path, monkeypatch):
    script = leaky_agent(tmp_path / "n", "'LEAK' in __import__('sys').stdin.read()")
    exp = leaky_exp(tmp_path, monkeypatch, script, tasks=6)
    leaking = replace(exp.arms[0], prompt_prefix="LEAK")
    exp = replace(exp, arms=(leaking, exp.arms[1]))
    summary = run_experiment(exp, tmp_path / "run")
    assert summary.isolation_halt
    assert sum(r.isolation_breach for r in records(tmp_path / "run")) == 3


def test_resuming_an_unfixed_leak_pays_for_one_more_attempt_not_three(tmp_path, monkeypatch):
    exp = leaky_exp(tmp_path, monkeypatch, leaky_agent(tmp_path / "n", "True"), arms=1, tasks=6)
    run_experiment(exp, tmp_path / "run")
    assert len(records(tmp_path / "run")) == 3
    again = run_experiment(exp, tmp_path / "run", resume=True)
    assert again.isolation_halt and len(records(tmp_path / "run")) == 4


def test_breach_attempts_do_not_use_up_retries(tmp_path, monkeypatch):
    # Breaches at attempts 0, 1, 2 across sessions, then the leak is fixed and a 429 hits.
    script = leaky_agent(tmp_path / "n", "n < 3").replace(
        "print(json.dumps({'type': 'result'",
        "if n == 3:\n"
        "    print(json.dumps({'type': 'result', 'is_error': True, 'api_error_status': 429}))\n"
        "    raise SystemExit(1)\n"
        "print(json.dumps({'type': 'result'",
    )
    exp = leaky_exp(tmp_path, monkeypatch, script, arms=1, tasks=1, max_retries=2)
    for _ in range(3):
        run_experiment(exp, tmp_path / "run", resume=(tmp_path / "run").exists())
    summary = run_experiment(exp, tmp_path / "run", resume=True)
    assert [r.status for r in records(tmp_path / "run")][3:] == ["error", "pass"]
    assert (summary.completed, summary.errors) == (1, 0)


def leaky_cli_config(tmp_path, monkeypatch, script) -> Path:
    leaky_exp(tmp_path, monkeypatch, script)  # registers the adapter
    task = tmp_path / "cli" / "tasks" / "t0"
    (task / "repo").mkdir(parents=True)
    (task / "repo" / "README.md").write_text("x\n", encoding="utf-8")
    (task / "task.toml").write_text(
        'prompt = "p"\ncheck = ["{python}", "-c", "pass"]\n', encoding="utf-8"
    )
    config = tmp_path / "cli" / "experiment.toml"
    config.write_text(
        'name = "x"\ntasks = ["tasks/*"]\nrepeats = 2\n'
        f"workspace_root = {json.dumps((tmp_path / 'ws').as_posix())}\n"
        f'[agent]\nadapter = "leaky"\noptions = {{ executable = {json.dumps(PY)} }}\n'
        '[[arms]]\nname = "a"\n',
        encoding="utf-8",
    )
    return config


def test_cli_does_not_call_a_run_with_a_breach_finished(tmp_path, monkeypatch, capsys):
    from agent_ab.cli import main

    config = leaky_cli_config(tmp_path, monkeypatch, leaky_agent(tmp_path / "n", "n == 0"))
    code = main(["run", str(config), "--out", str(tmp_path / "run"), "--quiet"])
    assert code == 1
    assert "--resume" in capsys.readouterr().err


def test_exhausted_errors_can_be_retried_without_discarding_paid_results(tmp_path):
    flag = tmp_path / "outage"
    flag.touch()
    script = (
        "import os, sys\n"
        f"{usage_snippet(cost_usd=1.0)}\n"
        f"{SOLVE}\n"
        f"if os.path.exists({str(flag)!r}) and "
        "os.path.basename(os.getcwd()).startswith('agent-ab-t1'):\n"
        f"    {usage_snippet(cost_usd=1.0, infra_error='outage')}\n"
    )
    tasks = [make_task(tmp_path, "t0"), make_task(tmp_path, "t1")]
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)], tasks=tasks, max_retries=1)
    first = run_experiment(exp, tmp_path / "run")
    assert (first.completed, first.errors) == (1, 1)
    flag.unlink()
    before = records(tmp_path / "run")
    run_experiment(exp, tmp_path / "run", resume=True)
    assert records(tmp_path / "run") == before  # still final without being asked

    summary = run_experiment(
        exp, tmp_path / "run", resume=True, options=RunOptions(retry_errors=True)
    )
    assert (summary.completed, summary.errors) == (2, 0)
    new = records(tmp_path / "run")[len(before) :]
    assert [(r.task, r.attempt, r.status) for r in new] == [("t1", 2, "pass")]
    assert records(tmp_path / "run")[: len(before)] == before
    assert RunStore.open(tmp_path / "run").total_cost() == pytest.approx(4.0)


def _fake_outcome_script(state: Path) -> str:
    return (
        "import json, os\n"
        f"mode = open({str(state)!r}).read().strip()\n"
        "usage = {'infra': {'infra_error': '429', 'cost_usd': 1.0},\n"
        "         'breach': {'infra_error': 'leak', 'isolation_breach': True}}[mode]\n"
        "path = os.path.join(os.environ['FAKE_ARTIFACTS'], 'usage.json')\n"
        "open(path, 'w').write(json.dumps(usage))\n"
    )


def test_fresh_retries_survive_a_breach_in_a_later_session(tmp_path):
    state = tmp_path / "mode"
    exp = make_exp(tmp_path, arms=[fake_arm("a", _fake_outcome_script(state))], max_retries=2)
    state.write_text("infra")
    run_experiment(exp, tmp_path / "run")
    state.write_text("breach")
    run_experiment(exp, tmp_path / "run", resume=True, options=RunOptions(retry_errors=True))
    state.write_text("infra")
    run_experiment(exp, tmp_path / "run", resume=True)
    assert [r.attempt for r in records(tmp_path / "run")] == [0, 1, 2, 3, 4, 5, 6]


def test_fresh_retries_survive_a_budget_stop(tmp_path):
    state = tmp_path / "mode"
    state.write_text("infra")
    exp = make_exp(tmp_path, arms=[fake_arm("a", _fake_outcome_script(state))], max_retries=2)
    run_experiment(exp, tmp_path / "run")
    options = RunOptions(retry_errors=True, budget_usd=4.0)
    run_experiment(exp, tmp_path / "run", resume=True, options=options)
    assert len(records(tmp_path / "run")) == 4
    summary = run_experiment(exp, tmp_path / "run", resume=True)
    assert [r.attempt for r in records(tmp_path / "run")] == [0, 1, 2, 3, 4, 5]
    assert summary.errors == 1


def test_retry_errors_needs_a_run_to_resume(tmp_path, monkeypatch):
    from agent_ab.cli import main

    config = leaky_cli_config(tmp_path, monkeypatch, leaky_agent(tmp_path / "n", "False"))
    code = main(["run", str(config), "--out", str(tmp_path / "run"), "--retry-errors"])
    assert code != 0 and not (tmp_path / "n").exists()


def test_outage_stops_the_run_before_exhausting_every_trial(tmp_path):
    tasks = [make_task(tmp_path, f"t{i:02}") for i in range(14)]
    script = usage_snippet(infra_error="429")
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)], tasks=tasks)
    summary = run_experiment(exp, tmp_path / "run")
    assert summary.infra_halt
    recs = records(tmp_path / "run")
    assert len(recs) == 10 and summary.errors == 0  # nothing used up: all can resume
    assert {r.attempt for r in recs} == {0}


def test_errors_in_one_arm_stop_it_though_the_other_arm_is_fine(tmp_path):
    tasks = [make_task(tmp_path, f"t{i:02}") for i in range(14)]
    arms = [fake_arm("a", usage_snippet(infra_error="401")), fake_arm("b", SOLVE)]
    summary = run_experiment(make_exp(tmp_path, arms=arms, tasks=tasks), tmp_path / "run")
    assert summary.infra_halt


def test_breach_flag_without_an_infra_error_cannot_pass(tmp_path):
    # A third-party adapter can set the flag alone; resume would re-run what stats counted.
    script = SOLVE + "\n" + usage_snippet(isolation_breach=True)
    rec = run_one(tmp_path, script)
    assert rec.status == "error" and rec.passed is None and rec.isolation_breach


def test_one_trial_using_all_its_retries_is_not_an_outage(tmp_path):
    arm = fake_arm("a", usage_snippet(infra_error="429"))
    exp = make_exp(tmp_path, arms=[arm], max_retries=10)
    summary = run_experiment(exp, tmp_path / "run")
    assert summary.infra_halt is None and summary.errors == 1
    assert len(records(tmp_path / "run")) == 11


def test_breaches_of_arms_outside_the_plan_do_not_count_toward_the_halt(tmp_path, monkeypatch):
    exp = leaky_exp(tmp_path, monkeypatch, leaky_agent(tmp_path / "n", "n == 0"), arms=1, tasks=2)
    store = RunStore.create(tmp_path / "run", exp, planned_trials=2)
    for i in range(3):
        store.append(TrialRecord(trial_id=f"x__z__r{i}", task="x", arm="z", repeat=i, attempt=0,
                                 status="error", isolation_breach=True))  # fmt: skip
    summary = run_experiment(exp, tmp_path / "run", resume=True)
    assert summary.isolation_halt is None


def test_log_failure_while_shutting_down_does_not_abandon_running_agents(tmp_path, monkeypatch):
    from agent_ab import runner

    real = runner.run_trial

    def then_interrupted(exp, spec, attempt, store, cancel, **kw):
        rec = real(exp, spec, attempt, store, cancel, **kw)
        cancel.set()
        return rec

    def full(self, record):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(runner, "run_trial", then_interrupted)
    monkeypatch.setattr(RunStore, "append", full)
    run_experiment(make_exp(tmp_path, arms=[fake_arm("a")]), tmp_path / "run")
    assert ws_left(tmp_path) == []


def test_attempt_that_finished_before_ctrl_c_is_kept(tmp_path, monkeypatch):
    from agent_ab import runner

    real = runner.run_trial

    def then_interrupted(exp, spec, attempt, store, cancel, **kw):
        rec = real(exp, spec, attempt, store, cancel, **kw)
        cancel.set()  # Ctrl-C arrives after the attempt finished, before it is collected
        return rec

    monkeypatch.setattr(runner, "run_trial", then_interrupted)
    arm = fake_arm("a", SOLVE + "\n" + usage_snippet(cost_usd=1.0))
    run_experiment(make_exp(tmp_path, arms=[arm]), tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "pass" and rec.cost_usd == 1.0


def test_stale_attempt_folder_that_cannot_be_removed_is_not_reused(tmp_path, monkeypatch):
    from agent_ab import runner

    exp = make_exp(tmp_path, arms=[fake_arm("a")])
    RunStore.create(tmp_path / "run", exp, planned_trials=1)
    stale = tmp_path / "run" / "trials" / "t1__a__r0" / "attempt-0"
    stale.mkdir(parents=True)
    (stale / "usage.json").write_text('{"cost_usd": 99.0}', encoding="utf-8")
    real = runner.destroy_workspace
    monkeypatch.setattr(
        runner, "destroy_workspace", lambda ws: False if Path(ws.path) == stale else real(ws)
    )
    run_experiment(exp, tmp_path / "run", resume=True)
    first, second = records(tmp_path / "run")
    assert first.status == "error" and first.cost_usd is None
    assert second.status == "pass" and second.cost_usd is None


def test_trial_with_no_leak_check_is_recorded_and_reported_as_unverified(tmp_path, monkeypatch):
    # A CLI release moves the init event: every trial is graded, none of them checked.
    result = "{'type': 'result', 'subtype': 'success', 'total_cost_usd': 0.1}"
    script = f"import json\n{SOLVE}\nprint(json.dumps({result}))\n"
    exp = leaky_exp(tmp_path, monkeypatch, script)
    run_experiment(exp, tmp_path / "run")
    store = RunStore.open(tmp_path / "run")
    recs = store.records()
    assert all(r.status == "pass" and r.leak_check == "unverified" for r in recs)
    noted = analyze(store.meta, recs).notes
    checked = [replace(r, leak_check="clean") for r in recs]
    assert set(noted) - set(analyze(store.meta, checked).notes)


def test_running_out_of_credit_stops_the_run_without_grading_anything(tmp_path, monkeypatch):
    result = (
        "{'type': 'result', 'subtype': 'success', 'is_error': True, 'api_error_status': 400, "
        "'result': 'Your credit balance is too low to access the Anthropic API.'}"
    )
    script = f"import json, sys\nprint(json.dumps({result}))\nsys.exit(1)\n"
    exp = leaky_exp(tmp_path, monkeypatch, script, arms=1, tasks=14)
    summary = run_experiment(exp, tmp_path / "run")
    assert summary.infra_halt and summary.completed == 0
    assert {r.status for r in records(tmp_path / "run")} == {"error"}


def test_halted_run_keeps_finished_trials_and_resumes(tmp_path, monkeypatch):
    # max_retries = 0: a breach must stay resumable even with no retries to spare.
    flag = tmp_path / "leak-is-unfixed"
    flag.touch()
    script = leaky_agent(tmp_path / "n", f"n > 0 and os.path.exists({str(flag)!r})")
    exp = leaky_exp(tmp_path, monkeypatch, script, max_retries=0)
    first = run_experiment(exp, tmp_path / "run")
    before = records(tmp_path / "run")
    assert first.isolation_halt and (first.completed, first.errors) == (1, 0)
    assert [r.status for r in before] == ["pass", "error", "error", "error"]

    flag.unlink()  # the owner fixes the leak
    second = run_experiment(exp, tmp_path / "run", resume=True)
    after = records(tmp_path / "run")
    assert second.isolation_halt is None
    assert (second.completed, second.errors) == (6, 0)
    assert after[:4] == before  # nothing finished was rewritten or run again
    assert len(after) == 9  # the three breached trials and the two never started, once each
    assert {r.attempt for r in after[4:] if r.trial_id == before[1].trial_id} == {1}


# --------------------------------------------------------------------------- isolation


def test_hidden_checks_not_visible_to_agent(tmp_path):
    task = make_task(tmp_path, check=(PY, "hidden_check.py"))
    checks = task.path / "checks"
    checks.mkdir()
    (checks / "hidden_check.py").write_text(
        "import os, sys\nsys.exit(0 if os.path.exists('solution.txt') else 1)\n", encoding="utf-8"
    )
    task = replace(task, checks=checks)
    script = f"import os, sys\nif os.path.exists('hidden_check.py'): sys.exit(9)\n{SOLVE}\n"
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)], tasks=[task])
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.agent_exit_code == 0 and rec.status == "pass"
    if HAS_GIT:
        assert rec.files_changed == 1  # the check file is not counted as an agent change


def test_overlay_and_remove_applied(tmp_path):
    overlay = tmp_path / "arms" / "b"
    overlay.mkdir(parents=True)
    (overlay / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    script = (
        "import os\n"
        "if os.path.exists('AGENTS.md') and not os.path.exists('README.md'):\n"
        f"    {SOLVE}\n"
    )
    exp = make_exp(
        tmp_path,
        arms=[fake_arm("a", script), fake_arm("b", script, overlay=overlay, remove=("README.md",))],
    )
    run_experiment(exp, tmp_path / "run")
    final = RunStore.open(tmp_path / "run").final_records()
    assert final["t1__a__r0"].status == "fail"
    assert final["t1__b__r0"].status == "pass"


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_diff_counts(tmp_path):
    script = (
        "open('a.txt', 'w').write('1\\n2\\n')\n"
        "open('b.txt', 'w').write('3\\n')\n"
        "open('README.md', 'w').write('changed\\n')\n"
    )
    rec = run_one(tmp_path, script)
    assert (rec.files_changed, rec.lines_added, rec.lines_removed) == (3, 4, 1)


def test_keep_workspaces(tmp_path):
    exp = make_exp(tmp_path, arms=[fake_arm("a")])
    run_experiment(exp, tmp_path / "run", options=RunOptions(keep_workspaces=True))
    (rec,) = records(tmp_path / "run")
    art = tmp_path / "run" / rec.artifacts
    kept = Path((art / "workspace.txt").read_text("utf-8").strip())
    assert kept.is_dir() and (kept / "solution.txt").is_file()
    graded = ws_left(tmp_path)
    if HAS_GIT:
        grade = Path((art / "grade-workspace.txt").read_text("utf-8").strip())
        assert (grade / "solution.txt").is_file()
        assert sorted(graded) == sorted([kept, grade])
    else:
        assert graded == [kept]


# --------------------------------------------------------------------------- scheduling


def test_budget_stops_launching(tmp_path):
    exp = make_exp(
        tmp_path,
        tasks=[make_task(tmp_path, "t1"), make_task(tmp_path, "t2"), make_task(tmp_path, "t3")],
        arms=[
            fake_arm("a", usage_snippet(cost_usd=1.0)),
            fake_arm("b", usage_snippet(cost_usd=1.0)),
        ],
        budget_usd=100.0,
    )
    events = []
    summary = run_experiment(
        exp, tmp_path / "run", options=RunOptions(budget_usd=2.5, progress=events.append)
    )
    assert len(records(tmp_path / "run")) == 3
    assert summary.budget_exhausted and summary.skipped_budget == 3
    assert summary.completed == 3 and summary.total_cost_usd == 3.0
    assert any(e.kind == "budget" for e in events)


def test_resume_completes_missing_trials(tmp_path):
    exp = make_exp(
        tmp_path,
        tasks=[make_task(tmp_path, "t1"), make_task(tmp_path, "t2")],
        arms=[
            fake_arm("a", usage_snippet(cost_usd=1.0)),
            fake_arm("b", usage_snippet(cost_usd=1.0)),
        ],
    )
    first = run_experiment(exp, tmp_path / "run", options=RunOptions(budget_usd=1.5))
    assert first.skipped_budget == 2
    before = records(tmp_path / "run")
    # Budget counts earlier sessions: still exhausted with the same limit.
    again = run_experiment(exp, tmp_path / "run", resume=True, options=RunOptions(budget_usd=1.5))
    assert again.budget_exhausted and len(records(tmp_path / "run")) == 2
    done = run_experiment(exp, tmp_path / "run", resume=True)
    after = records(tmp_path / "run")
    assert after[:2] == before
    assert len(after) == 4 and len({r.trial_id for r in after}) == 4
    assert done.completed == 4 and done.total_cost_usd == 4.0 and not done.budget_exhausted


def test_resume_continues_attempt_numbering(tmp_path):
    exp = make_exp(tmp_path, arms=[fake_arm("a"), fake_arm("b")])
    store = RunStore.create(tmp_path / "run", exp, planned_trials=2)
    store.append(
        TrialRecord(
            trial_id="t1__a__r0",
            task="t1",
            arm="a",
            repeat=0,
            attempt=0,
            status="error",
            error="earlier infra error",
        )
    )
    store.append(
        TrialRecord(
            trial_id="t1__b__r0",
            task="t1",
            arm="b",
            repeat=0,
            attempt=0,
            status="pass",
            passed=True,
        )
    )
    summary = run_experiment(exp, tmp_path / "run", resume=True)
    recs = records(tmp_path / "run")
    assert len(recs) == 3
    assert (recs[-1].trial_id, recs[-1].attempt, recs[-1].status) == ("t1__a__r0", 1, "pass")
    assert summary.completed == 2


def test_resume_updates_planned_trials(tmp_path):
    exp = make_exp(tmp_path)
    RunStore.create(tmp_path / "run", exp, planned_trials=99)
    run_experiment(exp, tmp_path / "run", resume=True)
    assert RunStore.open(tmp_path / "run").meta["planned_trials"] == 2


def test_resume_refuses_changed_fingerprint(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run", options=RunOptions(budget_usd=0.0))
    changed = replace(exp, fingerprint="different")
    with pytest.raises(RunStoreError):
        run_experiment(changed, tmp_path / "run", resume=True)
    summary = run_experiment(changed, tmp_path / "run", resume=True, options=RunOptions(force=True))
    assert summary.completed == 2


def test_new_run_refuses_existing_dir(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    with pytest.raises(RunStoreError):
        run_experiment(exp, tmp_path / "run")


def test_dry_run_creates_nothing(tmp_path):
    exp = make_exp(tmp_path, repeats=2)
    summary = run_experiment(exp, tmp_path / "run", options=RunOptions(dry_run=True))
    assert summary.planned == 4 and summary.completed == 0
    assert not (tmp_path / "run").exists() and not (tmp_path / "ws").exists()
    assert not (tmp_path / "runs").exists()
    run_experiment(exp, None, options=RunOptions(dry_run=True))
    assert not (tmp_path / "runs").exists()


def test_unavailable_adapter_fails_fast(tmp_path):
    exp = make_exp(
        tmp_path,
        arms=[
            fake_arm("a", options={"missing": "fake-cli not installed"}),
            fake_arm("b", options={"missing": "fake-cli too old"}),
        ],
    )
    with pytest.raises(AdapterError) as info:
        run_experiment(exp, tmp_path / "run")
    assert "not installed" in str(info.value) and "too old" in str(info.value)
    assert not (tmp_path / "run").exists()


def test_base_env_replaces_inherited_env_and_temp_dirs_are_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_AB_TEST_INHERITED", "x")
    script = (
        "import json, os\n"
        "seen = {k: os.environ.get(k) for k in ('AGENT_AB_TEST_INHERITED', 'BASE_ONLY')}\n"
        "seen['temp'] = os.path.isdir(os.environ['FAKE_TEMP'])\n"
        "json.dump(seen, open(os.path.join(os.environ['FAKE_ARTIFACTS'], 'seen.json'), 'w'))\n"
    )
    exp = make_exp(tmp_path, arms=[fake_arm("a", script, options={"isolate": True})])
    run_experiment(exp, tmp_path / "run")
    [rec] = records(tmp_path / "run")
    seen = json.loads((tmp_path / "run" / rec.artifacts / "seen.json").read_text("utf-8"))
    assert seen == {"AGENT_AB_TEST_INHERITED": None, "BASE_ONLY": "1", "temp": True}
    assert ws_left(tmp_path) == []  # the private directory beside the workspace is gone


def test_claude_isolation_checks_parents_of_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")  # isolation needs a credential
    (tmp_path / "CLAUDE.md").write_text("user rules\n", encoding="utf-8")
    arm = Arm(name="a", agent=AgentSpec(adapter="claude-code", options={"executable": PY}))
    exp = make_exp(tmp_path, arms=[arm])  # workspace_root = tmp_path / "ws"
    with pytest.raises(AdapterError) as info:
        run_experiment(exp, tmp_path / "run")
    assert str(tmp_path / "CLAUDE.md") in str(info.value)
    assert not (tmp_path / "run").exists()


def test_jobs_run_concurrently(tmp_path):
    script = (
        "import os, time\n"
        "s = time.time(); time.sleep(4.0)\n"
        "open(os.path.join(os.environ['FAKE_ARTIFACTS'], 'span.txt'), 'w')"
        ".write(f'{s} {time.time()}')\n"
    )
    exp = make_exp(
        tmp_path, arms=[fake_arm("a", script), fake_arm("b", script), fake_arm("c", script)], jobs=1
    )
    run_experiment(exp, tmp_path / "run", options=RunOptions(jobs=3))
    spans = [
        tuple(map(float, (tmp_path / "run" / r.artifacts / "span.txt").read_text().split()))
        for r in records(tmp_path / "run")
    ]
    assert len(spans) == 3
    assert max(s for s, _ in spans) < min(e for _, e in spans)  # all three overlapped


def test_keyboard_interrupt_cancels_without_half_records(tmp_path):
    exp = make_exp(tmp_path, arms=[fake_arm("a", HANG), fake_arm("b", HANG)], jobs=2)
    starts = []

    def progress(event):
        if event.kind == "start":
            starts.append(event)
            if len(starts) == 2:
                time.sleep(1.0)  # let both agents launch
                raise KeyboardInterrupt

    t0 = time.monotonic()
    summary = run_experiment(exp, tmp_path / "run", options=RunOptions(progress=progress))
    assert summary.cancelled and summary.completed == 0
    assert time.monotonic() - t0 < 20
    assert (tmp_path / "run" / TRIALS_FILE).read_text(encoding="utf-8") == ""
    assert ws_left(tmp_path) == []
    trials_dir = tmp_path / "run" / "trials"
    assert not trials_dir.exists() or not any(trials_dir.rglob("record.json"))


def test_run_trial_cancel_event(tmp_path):
    exp = make_exp(tmp_path, arms=[fake_arm("a", HANG)])
    store = RunStore.create(tmp_path / "run", exp, planned_trials=1)
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    spec = TrialSpec(task=exp.tasks[0], arm=exp.arms[0], repeat=0)
    rec = run_trial(exp, spec, 0, store, cancel)
    assert rec.error == "cancelled"
    assert not (tmp_path / "run" / "trials" / spec.id / "attempt-0").exists()
    assert ws_left(tmp_path) == []


# --------------------------------------------------------------------------- real mock adapter


def test_end_to_end_with_mock_adapter(tmp_path):
    pytest.importorskip("agent_ab.adapters.mock")
    adapters._INSTANCES.pop("mock", None)
    task = make_task(tmp_path)
    solution = task.path / "solution"
    solution.mkdir()
    (solution / "solution.txt").write_text("ok", encoding="utf-8")
    task = replace(task, solution=solution)
    arms = [
        Arm(name="weak", agent=AgentSpec(adapter="mock", options={"solve_rate": 0.0})),
        Arm(
            name="strong",
            agent=AgentSpec(adapter="mock", options={"solve_rate": 1.0, "cost_usd": 0.02}),
        ),
    ]
    exp = make_exp(tmp_path, arms=arms, tasks=[task], repeats=2, jobs=2)
    summary = run_experiment(exp, tmp_path / "run")
    final = RunStore.open(tmp_path / "run").final_records()
    assert summary.completed == 4 and summary.errors == 0
    assert {r.status for r in final.values() if r.arm == "strong"} == {"pass"}
    assert {r.status for r in final.values() if r.arm == "weak"} == {"fail"}
    assert summary.total_cost_usd == pytest.approx(0.02 * 2 + 0.01 * 2)
    assert ws_left(tmp_path) == []


def test_relative_run_dir_keeps_artifacts_out_of_workspace(tmp_path, monkeypatch):
    """A relative --out must not make agents write usage files into their workspace."""
    from agent_ab.store import RunStore

    monkeypatch.chdir(tmp_path)
    store = RunStore(Path("rel-run"))
    assert store.run_dir.is_absolute()
    assert store.attempt_dir("t__a__r0", 0).is_absolute()


# --------------------------------------------------------------------------- hostile agents


def raw_usage_snippet(raw: str) -> str:
    return (
        "import os; open(os.path.join(os.environ['FAKE_ARTIFACTS'], 'usage.json'), 'w')"
        f".write({raw!r}); open('solution.txt', 'w').write('ok')"
    )


@pytest.mark.parametrize("raw", [
    '{"cost_usd": 1e308, "input_tokens": 1' + "0" * 400 + ', "output_tokens": NaN,'
    ' "cache_read_tokens": -1, "turns": true, "cache_write_tokens": 5}',
    '{"cost_usd": 1' + "0" * 400 + ', "input_tokens": 1e3}',
    '{"cost_usd": NaN}',
])  # fmt: skip
def test_absurd_usage_is_dropped_not_fatal(tmp_path, raw):
    rec = run_one(tmp_path, raw_usage_snippet(raw), budget_usd=1.0)
    assert rec.status == "pass" and rec.error is None
    assert rec.cost_usd is None and rec.input_tokens is None and rec.output_tokens is None
    assert rec.cache_read_tokens is None and rec.turns is None
    art = tmp_path / "run" / rec.artifacts
    assert "implausible usage values dropped" in (art / "usage_warning.txt").read_text("utf-8")
    assert RunStore.open(tmp_path / "run").total_cost() == 0.0


def test_plausible_usage_is_kept(tmp_path):
    raw = '{"cost_usd": 2, "input_tokens": 10, "cache_write_tokens": 0}'
    rec = run_one(tmp_path, raw_usage_snippet(raw))
    assert rec.cost_usd == 2.0 and isinstance(rec.cost_usd, float)
    assert rec.input_tokens == 10 and rec.cache_write_tokens == 0
    assert not (tmp_path / "run" / rec.artifacts / "usage_warning.txt").exists()


def test_parser_crash_means_usage_unknown_not_infra_error(tmp_path):
    exp = make_exp(tmp_path, arms=[fake_arm("a", options={"script": SOLVE, "parse_error": True})])
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "pass" and rec.attempt == 0 and rec.cost_usd is None
    warning = (tmp_path / "run" / rec.artifacts / "usage_warning.txt").read_text("utf-8")
    assert "RecursionError" in warning


def test_grading_breakage_only_the_agents_diff_causes_is_fail(tmp_path, monkeypatch):
    from agent_ab import runner
    from agent_ab.errors import WorkspaceError

    real = runner.install_checks

    def broken(ws, task):
        if (ws.path / "solution.txt").exists():  # not on a copy without the agent's changes
            raise WorkspaceError("refusing to write outside the workspace")
        real(ws, task)

    monkeypatch.setattr(runner, "install_checks", broken)
    exp = make_exp(tmp_path, arms=[fake_arm("a")])
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")  # one attempt: nothing retried
    assert rec.status == "fail" and rec.passed is False
    assert (tmp_path / "run" / rec.artifacts / "traceback.txt").is_file()


def test_checks_folder_gone_after_the_agent_ran_is_infrastructure(tmp_path, monkeypatch):
    # A branch switch or moved folder during a long run: no copy of the task can be graded.
    from agent_ab import runner

    task = make_task(tmp_path)
    checks = task.path / "checks"
    checks.mkdir()
    (checks / "c.txt").write_text("x", encoding="utf-8")
    real = runner.diff_stats

    def moved_before_grading(ws, patch):
        shutil.rmtree(checks, ignore_errors=True)
        return real(ws, patch)

    monkeypatch.setattr(runner, "diff_stats", moved_before_grading)
    exp = make_exp(tmp_path, arms=[fake_arm("a")], tasks=[replace(task, checks=checks)])
    summary = run_experiment(exp, tmp_path / "run")
    recs = records(tmp_path / "run")
    assert [r.attempt for r in recs] == [0, 1, 2]  # retried like any infrastructure error
    assert all(r.status == "error" and r.passed is None for r in recs)
    assert (summary.completed, summary.errors) == (0, 1)
    assert ws_left(tmp_path) == []


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_full_disk_while_recording_the_diff_is_infrastructure(tmp_path, monkeypatch):
    from agent_ab import workspace as wsmod

    real = wsmod.subprocess.run

    def no_space(argv, **kw):
        if "add" in argv and (Path(kw["cwd"]) / "solution.txt").exists():
            stderr = b"error: unable to write loose object: No space left on device\n"
            return subprocess.CompletedProcess(argv, 128, b"", stderr)
        return real(argv, **kw)

    monkeypatch.setattr(wsmod.subprocess, "run", no_space)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "error" and rec.passed is None


def _git_fails(monkeypatch, when, outcome):
    """``outcome(argv)`` stands in for git where ``when(argv, cwd)`` holds."""
    from agent_ab import workspace as wsmod

    real = wsmod.subprocess.run

    def fake(argv, **kw):
        return outcome(argv) if when(argv, Path(kw["cwd"])) else real(argv, **kw)

    monkeypatch.setattr(wsmod.subprocess, "run", fake)


def _timeout(argv):
    raise subprocess.TimeoutExpired(argv, 600)


def _adds_agent_files(argv, cwd):
    return "add" in argv and (cwd / "solution.txt").exists()


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_git_apply_timing_out_on_the_clean_copy_is_infrastructure(tmp_path, monkeypatch):
    _git_fails(monkeypatch, lambda argv, cwd: "apply" in argv, _timeout)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "error" and rec.passed is None


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_git_apply_failing_to_write_a_valid_diff_is_infrastructure(tmp_path, monkeypatch):
    # Whatever git says: --check found nothing wrong with the diff, so writing it is the machine.
    def cannot_write(argv):
        return subprocess.CompletedProcess(argv, 1, b"", b"error: unable to write file 'x'\n")

    _git_fails(
        monkeypatch, lambda argv, cwd: "apply" in argv and "--check" not in argv, cannot_write
    )
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "error" and rec.passed is None


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_diff_git_refuses_after_the_check_stays_the_agents_failure(tmp_path, monkeypatch):
    def invalid(argv):
        return subprocess.CompletedProcess(argv, 1, b"", b"error: patch failed: x:1\n")

    _git_fails(monkeypatch, lambda argv, cwd: "apply" in argv and "--check" in argv, invalid)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "fail" and rec.passed is False


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_git_add_timing_out_on_a_small_workspace_is_infrastructure(tmp_path, monkeypatch):
    _git_fails(monkeypatch, _adds_agent_files, _timeout)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "error" and rec.passed is None


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_git_add_timing_out_on_a_big_task_is_the_machine(tmp_path, monkeypatch):
    # Size alone would blame the agent; it added one file to thirty of the task's.
    from agent_ab import workspace as wsmod

    monkeypatch.setattr(wsmod, "_GIT_MIN_FILES_PER_S", 3 / 600)
    _git_fails(monkeypatch, _adds_agent_files, _timeout)
    task = make_task(tmp_path)
    for i in range(30):
        (task.repo / f"f{i}.txt").write_text(str(i), encoding="utf-8")
    exp = make_exp(tmp_path, arms=[fake_arm("a")], tasks=[task], max_retries=0)
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "error" and rec.passed is None


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_git_add_timing_out_after_a_big_setup_is_the_machine(tmp_path, monkeypatch):
    from agent_ab import workspace as wsmod

    monkeypatch.setattr(wsmod, "_GIT_MIN_FILES_PER_S", 3 / 600)
    _git_fails(monkeypatch, _adds_agent_files, _timeout)
    setup = (PY, "-c", "for i in range(30): open('dep' + str(i), 'w').close()")
    rec = run_one(tmp_path, SOLVE, max_retries=0, task_kw={"setup": setup})
    assert rec.status == "error" and rec.passed is None


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_git_add_timing_out_on_a_workspace_the_agent_bloated_is_its_failure(tmp_path, monkeypatch):
    from agent_ab import workspace as wsmod

    monkeypatch.setattr(wsmod, "_GIT_MIN_FILES_PER_S", 3 / 600)  # the agent's files exceed it
    _git_fails(monkeypatch, _adds_agent_files, _timeout)
    script = SOLVE + "\nfor i in range(5):\n    open(f'junk{i}', 'w').close()\n"
    rec = run_one(tmp_path, script, max_retries=0)
    assert rec.status == "fail" and rec.passed is False


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_file_name_saying_no_space_left_stays_the_agents_failure(tmp_path, monkeypatch):
    def unreadable(argv):
        stderr = b'error: open("no space left on device.txt"): Permission denied\n'
        return subprocess.CompletedProcess(argv, 128, b"", stderr)

    _git_fails(monkeypatch, _adds_agent_files, unreadable)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "fail" and rec.passed is False


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_real_git_disk_full_message_with_a_later_line_is_infrastructure(tmp_path, monkeypatch):
    def no_space(argv):
        stderr = (
            b"error: unable to create temporary file: No space left on device\n"
            b"error: x: failed to insert into database\nfatal: adding files failed\n"
        )
        return subprocess.CompletedProcess(argv, 128, b"", stderr)

    _git_fails(monkeypatch, _adds_agent_files, no_space)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "error"


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
@pytest.mark.parametrize("winerror", [None, 206])
def test_gitlinks_overflowing_the_command_line_stay_the_agents_failure(
    tmp_path, monkeypatch, winerror
):
    # An agent can stage enough long gitlinks that dropping them does not fit on a command line.
    if winerror and os.name != "nt":
        pytest.skip("the winerror argument only exists on Windows")

    def too_long(argv):
        raise OSError(errno.E2BIG, "Argument list too long", None, winerror)

    _git_fails(monkeypatch, lambda argv, cwd: "update-index" in argv, too_long)
    script = (
        SOLVE + "\nimport subprocess\n"
        "line = '160000 ' + 'a' * 40 + ' 0\\tmodule\\n'\n"
        "subprocess.run(['git', 'update-index', '--add', '--index-info'], input=line.encode())\n"
    )
    rec = run_one(tmp_path, script, max_retries=0)
    assert rec.status == "fail" and rec.passed is False


def test_machine_out_of_memory_starting_the_check_is_infrastructure(tmp_path, monkeypatch):
    from agent_ab import proc

    real = proc.subprocess.Popen

    def no_memory(command, **kw):
        if command[0] == PY and (Path(kw["cwd"]) / "solution.txt").exists():  # the check
            raise OSError(errno.ENOMEM, "Cannot allocate memory")
        return real(command, **kw)

    monkeypatch.setattr(proc.subprocess, "Popen", no_memory)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "error" and rec.passed is None


@pytest.mark.parametrize("winerror", [8, 14, 39, 112, 1450, 1455])
@pytest.mark.skipif(os.name != "nt", reason="the winerror argument only exists on Windows")
def test_windows_out_of_resources_starting_the_check_is_infrastructure(
    tmp_path, monkeypatch, winerror
):
    from agent_ab import proc

    real = proc.subprocess.Popen

    def no_resources(command, **kw):
        if command[0] == PY and (Path(kw["cwd"]) / "solution.txt").exists():
            raise OSError(None, "out of resources", None, winerror)
        return real(command, **kw)

    monkeypatch.setattr(proc.subprocess, "Popen", no_resources)
    rec = run_one(tmp_path, SOLVE, max_retries=0)
    assert rec.status == "error" and rec.passed is None


def test_check_command_broken_for_every_copy_is_infrastructure(tmp_path):
    rec = run_one(
        tmp_path, SOLVE, task_kw={"check": ("agent-ab-no-such-check-exe",)}, max_retries=0
    )
    assert rec.status == "error" and rec.passed is None


def test_agent_deleting_the_check_script_is_fail(tmp_path):
    # The script lives in the task's repo and the agent's diff removes it: only its copy breaks.
    task = make_task(tmp_path)
    name = "run_check.cmd" if os.name == "nt" else "run_check.sh"
    body = "@exit /b 0\r\n" if os.name == "nt" else "#!/bin/sh\nexit 0\n"
    check = (f"{{workspace}}/{name}",)
    (task.repo / name).write_text(body, encoding="utf-8", newline="")
    os.chmod(task.repo / name, 0o755)
    script = f"import os; os.remove({name!r})"
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)], tasks=[replace(task, check=check)])
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "fail" and rec.check_exit_code is None


DELETE_WORKSPACE = (
    "import os, shutil, stat\n"
    "def unlock(f, p, e):\n"
    "    os.chmod(p, stat.S_IWRITE)\n"
    "    f(p)\n"
    "w = os.getcwd()\n"
    "os.chdir(os.path.dirname(w))\n"
    "shutil.rmtree(w, onerror=unlock)\n"
)


@pytest.mark.parametrize("git", [True, False])
def test_agent_deleting_its_workspace_is_fail(tmp_path, monkeypatch, git):
    from agent_ab import workspace as wsmod

    if not git:
        monkeypatch.setattr(wsmod, "_git", lambda: None)
    elif not HAS_GIT:
        pytest.skip("git not available")
    rec = run_one(tmp_path, DELETE_WORKSPACE)
    assert rec.status == "fail" and rec.attempt == 0, rec.error


def test_agent_link_over_checks_dir_is_replaced(tmp_path):
    task = make_task(tmp_path)
    checks = task.path / "checks" / "sub"
    checks.mkdir(parents=True)
    (checks / "helper.txt").write_text("hidden\n", encoding="utf-8")
    task = replace(task, checks=task.path / "checks")
    outside = tmp_path / "outside"
    outside.mkdir()
    # The agent swaps a checks path for a link (a junction on Windows) to a directory
    # outside the workspace.
    script = (
        "import os, subprocess, sys;"
        f"target = {str(outside)!r};"
        "subprocess.run(['cmd', '/c', 'mklink', '/J', 'sub', target], check=True,"
        " capture_output=True) if sys.platform == 'win32' else os.symlink(target, 'sub');"
        "open('solution.txt', 'w').write('ok')"
    )
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)], tasks=[task])
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "pass", rec.error
    assert list(outside.iterdir()) == []  # nothing written through the link
    assert ws_left(tmp_path) == []


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_deleting_the_snapshot_repository_fails_the_trial(tmp_path):
    # Without its diff the agent's work cannot be graded in a clean copy; grading in place
    # instead would reopen every workspace-level exploit.
    script = (
        "import os, shutil, stat\n"
        "def unlock(func, path, _):\n"
        "    os.chmod(path, stat.S_IWRITE)\n"
        "    func(path)\n"
        "shutil.rmtree('.git', onerror=unlock)\n"
        "open('solution.txt', 'w').write('ok')\n"
    )
    rec = run_one(tmp_path, script)
    assert rec.status == "fail" and rec.passed is False
    assert "could not be recorded" in rec.error
    assert ws_left(tmp_path) == []


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_nested_repository_created_by_the_agent_is_graded(tmp_path):
    # A vendored clone or `git init` in a subdirectory is ordinary work, not tampering.
    script = (
        "import os, subprocess\n"
        "os.makedirs('vendor', exist_ok=True)\n"
        "open(os.path.join('vendor', 'lib.py'), 'w').write('X = 1')\n"
        "subprocess.run(['git', 'init', '-q', 'vendor'], check=True)\n"
        "open('solution.txt', 'w').write('ok')\n"
    )
    rec = run_one(tmp_path, script)
    assert rec.status == "pass", rec.error
    assert rec.files_changed == 2
    assert ws_left(tmp_path) == []


CHECK_VENDORED = (
    PY,
    "-c",
    "import os, sys; sys.exit(0 if os.path.exists('solution.txt') "
    "and open(os.path.join('vendor', 'lib.py')).read() == 'X = 1' else 1)",
)
AGENT_GIT = (
    "g = ['git', '-c', 'user.name=x', '-c', 'user.email=x@x', '-c', 'commit.gpgsign=false']\n"
)


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_nested_repository_staged_by_the_agent_is_graded(tmp_path):
    # The agent commits in the nested repository and then stages everything in the workspace,
    # which leaves a gitlink in the index; its files must still reach the grading copy.
    script = (
        "import os, subprocess\n" + AGENT_GIT + "os.makedirs('vendor', exist_ok=True)\n"
        "open(os.path.join('vendor', 'lib.py'), 'w').write('X = 1')\n"
        "subprocess.run(g + ['init', '-q', 'vendor'], check=True)\n"
        "subprocess.run(g + ['-C', 'vendor', 'add', '.'], check=True)\n"
        "subprocess.run(g + ['-C', 'vendor', 'commit', '-qm', 'v'], check=True)\n"
        "open('solution.txt', 'w').write('ok')\n"
        "subprocess.run(g + ['add', '-A'], check=True)\n"
        "subprocess.run(g + ['commit', '-qm', 'work'], check=True)\n"
    )
    rec = run_one(tmp_path, script, task_kw={"check": CHECK_VENDORED}, max_retries=0)
    assert rec.status == "pass", rec.error


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_submodule_added_by_the_agent_is_graded(tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "lib.py").write_text("X = 1", encoding="utf-8")
    git = ["git", "-c", "user.name=x", "-c", "user.email=x@x", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q", str(upstream)], check=True)
    subprocess.run([*git, "-C", str(upstream), "add", "."], check=True)
    subprocess.run([*git, "-C", str(upstream), "commit", "-qm", "v"], check=True)
    script = (
        "import subprocess\n" + AGENT_GIT + "subprocess.run(g + "
        "['-c', 'protocol.file.allow=always', "
        f"'submodule', 'add', '-q', {upstream.as_posix()!r}, 'vendor'], check=True)\n"
        "open('solution.txt', 'w').write('ok')\n"
    )
    rec = run_one(tmp_path, script, task_kw={"check": CHECK_VENDORED}, max_retries=0)
    assert rec.status == "pass", rec.error


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_agent_configured_git_filter_does_not_run_while_recording(tmp_path):
    # A clean filter named in .gitattributes would otherwise run agent code inside agent-ab's
    # own `git add`, after the agent's processes were killed.
    marker = tmp_path / "filter-ran.txt"
    filt = tmp_path / "filt.py"
    filt.write_text(
        "import sys\n"
        f"open({str(marker)!r}, 'w').write('x')\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    cmd = f'"{Path(PY).as_posix()}" "{filt.as_posix()}"'
    script = (
        "import subprocess\n"
        "open('solution.txt', 'w').write('ok')\n"
        "open('.gitattributes', 'w').write('solution.txt filter=x\\n')\n"
        f"subprocess.run(['git', 'config', 'filter.x.clean', {cmd!r}], check=True)\n"
    )
    rec = run_one(tmp_path, script, max_retries=0)
    assert rec.status == "pass", rec.error
    assert not marker.exists()


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_grading_copy_snapshot_failure_is_an_infrastructure_error(tmp_path, monkeypatch):
    # The grading copy is pristine, so failing to snapshot it after setup is not the agent's.
    from agent_ab import runner
    from agent_ab.errors import WorkspaceError

    real = runner.rebaseline
    calls = []

    def flaky(ws):
        calls.append(ws)
        if len(calls) == 2:  # the grading copy's rebaseline
            raise WorkspaceError("disk full")
        real(ws)

    monkeypatch.setattr(runner, "rebaseline", flaky)
    setup = (PY, "-c", "open('gen.txt', 'w').write('x')")
    rec = run_one(tmp_path, SOLVE, task_kw={"setup": setup}, max_retries=0)
    assert rec.status == "error", rec.error
    assert "grading copy" in rec.error and "disk full" in rec.error


def test_new_run_refuses_dir_with_stale_trial_log(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / TRIALS_FILE).write_text("{}\n", encoding="utf-8")
    with pytest.raises(RunStoreError, match="no run.json"):
        run_experiment(make_exp(tmp_path), run)
    assert not (run / "run.json").exists()
    assert ws_left(tmp_path) == []


def test_resume_ignores_records_outside_the_plan(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    store = RunStore.open(tmp_path / "run")
    store.append(
        TrialRecord(
            trial_id="gone__a__r0",
            task="gone",
            arm="a",
            repeat=0,
            attempt=0,
            status="pass",
            passed=True,
        )
    )
    events = []
    summary = run_experiment(
        exp, tmp_path / "run", resume=True, options=RunOptions(progress=events.append)
    )
    assert summary.planned == 2 and summary.completed == 2
    assert any("not in the current plan" in e.message for e in events if e.kind == "info")


def test_leaked_workspace_is_noted(tmp_path, monkeypatch):
    from agent_ab import runner

    monkeypatch.setattr(runner, "destroy_workspace", lambda ws: False)
    exp = make_exp(tmp_path, arms=[fake_arm("a")])
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    note = tmp_path / "run" / rec.artifacts / "workspace-leaked.txt"
    leaked = ws_left(tmp_path)
    assert len(leaked) == (2 if HAS_GIT else 1)  # the agent's workspace and the grading copy
    assert sorted(note.read_text(encoding="utf-8").split()) == sorted(map(str, leaked))
    for path in leaked:
        shutil.rmtree(path, ignore_errors=True)


def test_record_hashes_prompt_and_instruction_files(tmp_path):
    import hashlib

    overlay = tmp_path / "overlay"
    (overlay / ".claude").mkdir(parents=True)
    (overlay / "CLAUDE.md").write_bytes(b"Write tests first.\n")
    (overlay / ".claude" / "CLAUDE.md").write_bytes(b"nested\n")
    exp = make_exp(
        tmp_path,
        arms=[fake_arm("a"), fake_arm("b", overlay=overlay, prompt_prefix="Be careful.")],
    )
    run_experiment(exp, tmp_path / "run")
    final = RunStore.open(tmp_path / "run").final_records()
    a, b = final["t1__a__r0"], final["t1__b__r0"]
    for rec in (a, b):
        sent = (tmp_path / "run" / rec.artifacts / "prompt.md").read_bytes()
        assert sent.endswith(b"\n")
        assert rec.prompt_sha256 == hashlib.sha256(sent[:-1]).hexdigest()
    assert a.prompt_sha256 != b.prompt_sha256
    assert a.instructions_sha256 is None
    assert b.instructions_sha256 == {
        "CLAUDE.md": hashlib.sha256(b"Write tests first.\n").hexdigest(),
        ".claude/CLAUDE.md": hashlib.sha256(b"nested\n").hexdigest(),
    }


def test_instruction_hashes_include_adapter_files(tmp_path):
    from agent_ab.runner import _instruction_hashes
    from agent_ab.workspace import Workspace

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("a\n", encoding="utf-8")
    extra = tmp_path / "append_system_prompt.md"
    extra.write_text("b", encoding="utf-8")
    found = _instruction_hashes(Workspace(path=ws), [extra, tmp_path / "missing.md"])
    assert sorted(found) == ["AGENTS.md", "agent:append_system_prompt.md"]


# --------------------------------------------------------------------------- forced resumes


def _drop_last_record(run_dir: Path) -> None:
    log = run_dir / TRIALS_FILE
    log.write_text("".join(log.read_text("utf-8").splitlines(True)[:-1]), "utf-8", newline="\n")


def test_resume_under_another_agent_ab_version_needs_force(tmp_path, monkeypatch):
    from agent_ab import __version__, runner
    from agent_ab import store as storemod

    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    _drop_last_record(tmp_path / "run")
    monkeypatch.setattr(storemod, "__version__", "9.9.9")
    monkeypatch.setattr(runner, "__version__", "9.9.9")
    with pytest.raises(RunStoreError):
        run_experiment(exp, tmp_path / "run", resume=True)
    assert len(records(tmp_path / "run")) == 1

    run_experiment(exp, tmp_path / "run", resume=True, options=RunOptions(force=True))
    meta = RunStore.open(tmp_path / "run").meta
    assert [f["version"] for f in meta["forced_resumes"]] == ["9.9.9"]
    assert {r.tool_version for r in records(tmp_path / "run")} == {__version__, "9.9.9"}
    # What was forced is accepted from here on; the log and report show the mix.
    run_experiment(exp, tmp_path / "run", resume=True)
    assert len(RunStore.open(tmp_path / "run").meta["forced_resumes"]) == 1
    full = analyze(meta, records(tmp_path / "run"))
    bare = analyze({k: v for k, v in meta.items() if k != "forced_resumes"}, [
        replace(r, tool_version=None) for r in records(tmp_path / "run")
    ])  # fmt: skip
    assert set(full.notes) - set(bare.notes)


@pytest.mark.skipif(not HAS_GIT, reason="git not available")
def test_resume_without_git_after_clean_copy_grading_needs_force(tmp_path, monkeypatch):
    from agent_ab import workspace as wsmod

    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    _drop_last_record(tmp_path / "run")
    monkeypatch.setattr(wsmod, "_git", lambda: None)
    with pytest.raises(RunStoreError):
        run_experiment(exp, tmp_path / "run", resume=True)
    run_experiment(exp, tmp_path / "run", resume=True, options=RunOptions(force=True))
    assert [r.grading for r in records(tmp_path / "run")] == ["clean-copy", "agent-workspace"]


def test_resume_of_a_run_without_recorded_grading_needs_force(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    _drop_last_record(tmp_path / "run")
    path = tmp_path / "run" / "run.json"
    meta = json.loads(path.read_text("utf-8"))
    del meta["grading"]
    path.write_text(json.dumps(meta), "utf-8")
    with pytest.raises(RunStoreError):
        run_experiment(exp, tmp_path / "run", resume=True)


def test_forcing_an_old_run_does_not_claim_its_definition_changed(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    _drop_last_record(tmp_path / "run")
    path = tmp_path / "run" / "run.json"
    meta = json.loads(path.read_text("utf-8"))
    del meta["grading"]  # as a run from before these fields existed
    path.write_text(json.dumps(meta), "utf-8")
    log = tmp_path / "run" / TRIALS_FILE
    old = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
    log.write_text("".join(json.dumps({**r, "fingerprint": None}) + "\n" for r in old), "utf-8")
    run_experiment(exp, tmp_path / "run", resume=True, options=RunOptions(force=True))
    store = RunStore.open(tmp_path / "run")
    assert store.meta["forced_resumes"][0]["from_fingerprint"] == exp.fingerprint
    notes = analyze(store.meta, store.records()).notes
    assert not any(" of 2 recorded trials" in n for n in notes)


def test_forced_change_counts_only_trials_known_or_possibly_under_the_old_definition(tmp_path):
    arm = fake_arm("a")
    exp = make_exp(tmp_path, arms=[arm], repeats=1)
    run_experiment(exp, tmp_path / "run")
    more = make_exp(tmp_path, arms=[arm], repeats=3)
    run_experiment(more, tmp_path / "run", resume=True, options=RunOptions(force=True))
    store = RunStore.open(tmp_path / "run")
    assert any("1 of 3 recorded trials" in n for n in analyze(store.meta, store.records()).notes)


def test_forced_more_repeats_enter_the_analysis_and_total_cost(tmp_path):
    arm = fake_arm("a", SOLVE + "\n" + usage_snippet(cost_usd=1.0))
    exp = make_exp(tmp_path, arms=[arm], repeats=1)
    run_experiment(exp, tmp_path / "run")
    more = make_exp(tmp_path, arms=[arm], repeats=3)
    run_experiment(more, tmp_path / "run", resume=True, options=RunOptions(force=True))
    store = RunStore.open(tmp_path / "run")
    a = analyze(store.meta, store.records())
    assert (a.completed_trials, a.planned_trials) == (3, 3)
    assert a.total_cost_usd == pytest.approx(3.0)
    assert store.meta["fingerprint"] == more.fingerprint and store.meta["forced_resumes"]


def test_forced_narrower_selection_reports_and_counts_the_new_plan(tmp_path, capsys):
    from agent_ab.cli import main

    arms = [fake_arm(n, SOLVE + "\n" + usage_snippet(cost_usd=1.0)) for n in "ab"]
    tasks = [make_task(tmp_path, f"t{i}") for i in range(3)]
    exp = make_exp(tmp_path, arms=arms, tasks=tasks, budget_usd=2.0)
    run_experiment(exp, tmp_path / "run")
    assert len(records(tmp_path / "run")) == 2
    only_a = make_exp(tmp_path, arms=arms[:1], tasks=tasks)
    run_experiment(only_a, tmp_path / "run", resume=True, options=RunOptions(force=True))
    store = RunStore.open(tmp_path / "run")
    a = analyze(store.meta, store.records())
    assert [s.arm for s in a.arms] == ["a"]
    assert (a.completed_trials, a.planned_trials) == (3, 3)
    capsys.readouterr()
    assert main(["status", str(tmp_path / "run")]) == 0
    assert "3/3 done" in capsys.readouterr().out


# --------------------------------------------------------------------------- run-directory lock

HOLD_LOCK = """
import sys, time
from pathlib import Path
from agent_ab.store import RunLock
lock = RunLock()
lock.acquire(Path(sys.argv[1]))
print("held", flush=True)
time.sleep(30)  # a test that forgets to kill this cannot hang for long
"""


def hold_lock(run_dir: Path) -> subprocess.Popen:
    proc = subprocess.Popen([PY, "-c", HOLD_LOCK, str(run_dir)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def test_second_session_refused_until_the_first_crashes(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    _drop_last_record(tmp_path / "run")
    holder = hold_lock(tmp_path / "run")
    try:
        with pytest.raises(RunStoreError):
            run_experiment(exp, tmp_path / "run", resume=True)
        assert len(records(tmp_path / "run")) == 1  # refused before anything ran
        # Reading is not running: a dry run and the reports still work.
        run_experiment(exp, tmp_path / "run", resume=True, options=RunOptions(dry_run=True))
    finally:
        holder.kill()  # a crash: nothing gets to release the lock
        holder.wait(timeout=30)
        holder.stdout.close()
    summary = run_experiment(exp, tmp_path / "run", resume=True)
    assert summary.completed == 2 and len(records(tmp_path / "run")) == 2


def test_new_run_refused_while_its_directory_is_locked(tmp_path):
    exp = make_exp(tmp_path)
    (tmp_path / "run").mkdir()
    holder = hold_lock(tmp_path / "run")
    try:
        with pytest.raises(RunStoreError):
            run_experiment(exp, tmp_path / "run")
        assert not (tmp_path / "run" / "run.json").exists()
    finally:
        holder.kill()
        holder.wait(timeout=30)
        holder.stdout.close()


def test_lock_is_released_after_a_session_so_the_next_can_start(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    _drop_last_record(tmp_path / "run")
    assert run_experiment(exp, tmp_path / "run", resume=True).completed == 2


# --------------------------------------------------------------------------- small state fixes


def test_record_json_failure_does_not_put_an_error_on_a_pass(tmp_path, monkeypatch):
    from agent_ab import runner

    real = runner._write_text

    def refuse(path, text):
        if path.name == "record.json":
            raise OSError("no")
        real(path, text)

    monkeypatch.setattr(runner, "_write_text", refuse)
    rec = run_one(tmp_path, SOLVE)
    assert rec.status == "pass" and rec.error is None


def test_status_marks_reports_older_than_the_log(tmp_path, capsys):
    from agent_ab.cli import main

    run_experiment(make_exp(tmp_path), tmp_path / "run")
    report = tmp_path / "run" / "report.md"
    report.write_text("x", encoding="utf-8")
    capsys.readouterr()
    main(["status", str(tmp_path / "run")])
    fresh = capsys.readouterr().out
    os.utime(report, (1, 1))
    main(["status", str(tmp_path / "run")])
    assert capsys.readouterr().out != fresh


def test_status_does_not_call_reports_stale_for_a_newer_file_time_on_the_log(tmp_path, capsys):
    # A fresh git checkout gives every file an arbitrary time; what the log holds is what counts.
    from agent_ab.cli import main

    run_experiment(make_exp(tmp_path), tmp_path / "run")
    (tmp_path / "run" / "report.md").write_text("x", encoding="utf-8")
    capsys.readouterr()
    main(["status", str(tmp_path / "run")])
    fresh = capsys.readouterr().out
    log = tmp_path / "run" / TRIALS_FILE
    later = time.time() + 1000
    os.utime(log, (later, later))
    main(["status", str(tmp_path / "run")])
    assert capsys.readouterr().out == fresh


def in_use(run_dir: Path) -> list[str]:
    folder = run_dir / "workspaces-in-use"
    lines = [line for f in sorted(folder.glob("*")) for line in f.read_text("utf-8").splitlines()]
    return [line.rsplit("\t", 1)[0] for line in lines]


def test_cancelled_attempt_keeps_a_pointer_to_what_it_leaked(tmp_path, monkeypatch):
    from agent_ab import runner

    cancel = threading.Event()
    real = runner.destroy_workspace
    monkeypatch.setattr(
        runner,
        "destroy_workspace",
        lambda ws: False if Path(ws.path).name.startswith("agent-ab-") else real(ws),
    )
    real_prompt = runner._build_prompt

    def interrupted(spec):
        cancel.set()
        return real_prompt(spec)

    monkeypatch.setattr(runner, "_build_prompt", interrupted)
    exp = make_exp(tmp_path, arms=[fake_arm("a")])
    store = RunStore.create(tmp_path / "run", exp, planned_trials=1)
    rec = run_trial(exp, plan_trials(exp)[0], 0, store, cancel)
    assert rec.error == "cancelled"
    leaked = ws_left(tmp_path)
    assert leaked and sorted(in_use(tmp_path / "run")) == sorted(map(str, leaked))
    for path in leaked:
        shutil.rmtree(path, ignore_errors=True)


def test_leaked_private_directory_gets_a_pointer(tmp_path, monkeypatch):
    from agent_ab import runner

    real = runner.destroy_workspace
    monkeypatch.setattr(
        runner, "destroy_workspace", lambda ws: False if ".private" in str(ws.path) else real(ws)
    )
    exp = make_exp(tmp_path, arms=[fake_arm("a", options={"isolate": True})])
    run_experiment(exp, tmp_path / "run")
    (leaked,) = ws_left(tmp_path)
    assert in_use(tmp_path / "run") == [str(leaked)]
    shutil.rmtree(leaked, ignore_errors=True)


def test_leak_under_keep_workspaces_does_not_get_kept_ones_swept(tmp_path, monkeypatch):
    from agent_ab import runner

    real = runner.destroy_workspace
    with monkeypatch.context() as m:
        m.setattr(
            runner,
            "destroy_workspace",
            lambda ws: False if ".private" in str(ws.path) else real(ws),
        )
        exp = make_exp(
            tmp_path, arms=[fake_arm("a", options={"isolate": True})], keep_workspaces=True
        )
        run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    kept = Path((tmp_path / "run" / rec.artifacts / "workspace.txt").read_text("utf-8").strip())
    (leaked,) = in_use(tmp_path / "run")
    assert leaked.endswith(".private")
    run_experiment(exp, tmp_path / "run", resume=True)
    assert kept.is_dir() and not Path(leaked).exists()
    for path in ws_left(tmp_path):
        shutil.rmtree(path, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))


def test_resume_removes_workspaces_a_crash_left_and_nothing_else(tmp_path):
    exp = make_exp(tmp_path)
    run_experiment(exp, tmp_path / "run")
    _drop_last_record(tmp_path / "run")
    from agent_ab.runner import _LiveDirs

    orphan = tmp_path / "ws" / "agent-ab-t1__b__r0-a0-orphan"
    orphan.mkdir(parents=True)
    _LiveDirs(RunStore.open(tmp_path / "run"), "t1__b__r0", 0).add(orphan)
    folder = tmp_path / "run" / "workspaces-in-use"
    run_experiment(exp, tmp_path / "run", resume=True)
    assert not orphan.exists()
    assert not folder.exists()


def test_sweep_leaves_whatever_it_cannot_prove_it_created(tmp_path):
    from agent_ab.runner import _LiveDirs

    exp = make_exp(tmp_path)
    label = "agent-ab-t1__b__r0-a0"
    run = tmp_path / f"{label}-the-run-itself"
    run_experiment(exp, run)
    _drop_last_record(run)
    live = _LiveDirs(RunStore.open(run), "t1__b__r0", 0)
    # Each of these would pass a check of the name alone, or carries a real stamp.
    fork = tmp_path / "elsewhere" / "agent-ab-fork"
    root = tmp_path / "elsewhere" / "agent-ab-workspaces"
    another_trial = tmp_path / "ws" / "agent-ab-t2__b__r0-a0-live"
    for path in (fork, root, another_trial):
        path.mkdir(parents=True)
        live.add(path)
    live.add(run)  # the run directory itself, correctly named and stamped
    live.add(tmp_path)  # a folder holding the run directory
    no_stamp = tmp_path / "ws" / f"{label}-unstamped"
    swapped = tmp_path / "ws" / f"{label}-swapped"
    no_stamp.mkdir()
    swapped.mkdir()
    live.add(swapped)  # stamped, then replaced by another folder of the same name
    swapped.rmdir()
    placeholder = tmp_path / "ws" / "occupy-the-inode"
    placeholder.mkdir()
    swapped.mkdir()
    with open(live.file, "a", encoding="utf-8") as f:
        f.write(f"{no_stamp}\n")
    summary = run_experiment(exp, run, resume=True)
    assert summary.completed == 2
    survivors = (fork, root, another_trial, no_stamp, swapped)
    assert all(path.is_dir() for path in survivors)
    assert (run / "run.json").is_file() and (run / "trials").is_dir()
    assert str(fork) in in_use(run)  # still listed for a person to look at


def test_crash_while_creating_a_run_leaves_a_directory_that_can_be_used(tmp_path, monkeypatch):
    exp = make_exp(tmp_path)

    def crash(self):
        raise KeyboardInterrupt

    with monkeypatch.context() as m:
        m.setattr(RunStore, "_write_meta", crash)
        with pytest.raises(KeyboardInterrupt):
            run_experiment(exp, tmp_path / "run")
    assert run_experiment(exp, tmp_path / "run").completed == 2


def test_claude_parser_crash_means_usage_unknown(tmp_path, monkeypatch):
    from agent_ab.adapters import claude_code

    def boom(*a):
        raise RecursionError("too deep")

    monkeypatch.setattr(claude_code, "parse_result_text", boom)
    exp = leaky_exp(tmp_path, monkeypatch, leaky_agent(tmp_path / "n", "False"), arms=1, tasks=1)
    run_experiment(exp, tmp_path / "run")
    (rec,) = records(tmp_path / "run")
    assert rec.status == "pass" and rec.cost_usd is None and rec.leak_check == "unverified"


def test_manipulation_script_counts_only_what_the_report_counts(tmp_path):
    import importlib.util

    root = Path(__file__).parent.parent
    spec = importlib.util.spec_from_file_location(
        "manipulation", root / "docs" / "results" / "manipulation.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def line(tid, attempt, status):
        task, arm, _ = tid.split("__")
        return dict(trial_id=tid, task=task, arm=arm, repeat=0, attempt=attempt, status=status)

    lines = [
        line("t__a__r0", 1, "pass"),
        line("t__a__r0", 0, "error"),  # out of order: the higher attempt still wins
        line("u__a__r0", 2, "error"),  # excluded from the report
        line("t__z__r0", 0, "pass"),  # outside the plan
    ]
    (tmp_path / "trials.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), "utf-8")
    config = {"tasks": [{"id": "t"}, {"id": "u"}], "arms": [{"name": "a"}], "repeats": 1}
    (tmp_path / "run.json").write_text(json.dumps({"config": config}), "utf-8")
    assert [r["trial_id"] for r in mod.final_records(tmp_path)] == ["t__a__r0"]
