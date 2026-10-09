import json
import shutil
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agent_ab import adapters
from agent_ab.adapters.base import Adapter
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
    option_keys = frozenset({"script", "missing", "build_error", "argv"})

    def check_available(self, spec: AgentSpec) -> str | None:
        return spec.options.get("missing")

    def build(self, ctx: TrialContext) -> AgentInvocation:
        if ctx.spec.options.get("build_error"):
            raise RuntimeError("boom in build")
        argv = ctx.spec.options.get("argv") or [PY, "-c", ctx.spec.options.get("script", "")]
        env = {"FAKE_ATTEMPT": str(ctx.attempt), "FAKE_ARTIFACTS": str(ctx.artifacts)}
        return AgentInvocation(argv=list(argv), env=env)

    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
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
    fields = {"id": tid, "path": task_dir, "prompt": "Write solution.txt.", "check": CHECK_SOLVED,
              "repo": repo}
    fields.update(kw)
    return Task(**fields)


def fake_arm(name: str, script: str = SOLVE, **kw) -> Arm:
    options = kw.pop("options", {})
    return Arm(name=name, agent=AgentSpec(adapter="fake", options={"script": script, **options}),
               **kw)


def make_exp(tmp_path: Path, arms=None, tasks=None, **kw) -> Experiment:
    arms = tuple(arms or (fake_arm("a"), fake_arm("b")))
    tasks = tuple(tasks or (make_task(tmp_path),))
    fields = {"repeats": 1, "jobs": 1, "max_retries": 2, "timeout_s": 60.0,
              "check_timeout_s": 60.0, "workspace_root": tmp_path / "ws"}
    fields.update(kw)
    exp = Experiment(name="exp", config_path=tmp_path / "experiment.toml", root=tmp_path,
                     tasks=tasks, arms=arms, baseline=arms[0].name, **fields)
    return replace(exp, fingerprint=compute_fingerprint(exp))


def records(run_dir: Path) -> list[TrialRecord]:
    return RunStore.open(run_dir).records()


def ws_left(tmp_path: Path) -> list[Path]:
    root = tmp_path / "ws"
    return list(root.iterdir()) if root.exists() else []


def run_one(tmp_path: Path, script: str, **kw) -> TrialRecord:
    """Run a single-arm, single-task experiment and return the only final record."""
    task_kw = kw.pop("task_kw", {})
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)], tasks=[make_task(tmp_path, **task_kw)],
                   **kw)
    summary = run_experiment(exp, tmp_path / "run")
    assert summary.planned == 1
    final = RunStore.open(tmp_path / "run").final_records()
    assert ws_left(tmp_path) == []
    return final["t1__a__r0"]


# --------------------------------------------------------------------------- planning


def test_plan_is_complete_and_deterministic(tmp_path):
    exp = make_exp(tmp_path, tasks=[make_task(tmp_path, "t1"), make_task(tmp_path, "t2")],
                   repeats=3, seed=7)
    ids = [s.id for s in plan_trials(exp)]
    assert len(ids) == len(set(ids)) == 12
    assert ids == [s.id for s in plan_trials(exp)]
    assert ids != [s.id for s in plan_trials(replace(exp, seed=8))]


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
    for name in ("prompt.md", "agent.stdout", "agent.stderr", "check.stdout", "check.stderr",
                 "record.json"):
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
    rec = run_one(tmp_path, script, timeout_s=1.5, timeout_is_failure=False)
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
    exp = make_exp(tmp_path, max_retries=0,
                   arms=[fake_arm("a", options={"argv": ["no-such-agent-binary-xyz"]})])
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
    exp = make_exp(tmp_path, max_retries=2,
                   arms=[fake_arm("a", usage_snippet(infra_error="down"))])
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
    exp = make_exp(tmp_path, arms=[fake_arm("a", script),
                                   fake_arm("b", script, overlay=overlay, remove=("README.md",))])
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
    kept = Path((tmp_path / "run" / rec.artifacts / "workspace.txt").read_text("utf-8").strip())
    assert kept.is_dir() and (kept / "solution.txt").is_file()
    assert ws_left(tmp_path) == [kept]


# --------------------------------------------------------------------------- scheduling


def test_budget_stops_launching(tmp_path):
    exp = make_exp(tmp_path, tasks=[make_task(tmp_path, "t1"), make_task(tmp_path, "t2"),
                                    make_task(tmp_path, "t3")],
                   arms=[fake_arm("a", usage_snippet(cost_usd=1.0)),
                         fake_arm("b", usage_snippet(cost_usd=1.0))],
                   budget_usd=100.0)
    events = []
    summary = run_experiment(exp, tmp_path / "run",
                             options=RunOptions(budget_usd=2.5, progress=events.append))
    assert len(records(tmp_path / "run")) == 3
    assert summary.budget_exhausted and summary.skipped_budget == 3
    assert summary.completed == 3 and summary.total_cost_usd == 3.0
    assert any(e.kind == "budget" for e in events)


def test_resume_completes_missing_trials(tmp_path):
    exp = make_exp(tmp_path, tasks=[make_task(tmp_path, "t1"), make_task(tmp_path, "t2")],
                   arms=[fake_arm("a", usage_snippet(cost_usd=1.0)),
                         fake_arm("b", usage_snippet(cost_usd=1.0))])
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
    store.append(TrialRecord(trial_id="t1__a__r0", task="t1", arm="a", repeat=0, attempt=0,
                             status="error", error="earlier infra error"))
    store.append(TrialRecord(trial_id="t1__b__r0", task="t1", arm="b", repeat=0, attempt=0,
                             status="pass", passed=True))
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
    exp = make_exp(tmp_path, arms=[fake_arm("a", options={"missing": "fake-cli not installed"}),
                                   fake_arm("b", options={"missing": "fake-cli too old"})])
    with pytest.raises(AdapterError) as info:
        run_experiment(exp, tmp_path / "run")
    assert "not installed" in str(info.value) and "too old" in str(info.value)
    assert not (tmp_path / "run").exists()


def test_jobs_run_concurrently(tmp_path):
    script = (
        "import os, time\n"
        "s = time.time(); time.sleep(1.0)\n"
        "open(os.path.join(os.environ['FAKE_ARTIFACTS'], 'span.txt'), 'w')"
        ".write(f'{s} {time.time()}')\n"
    )
    exp = make_exp(tmp_path, arms=[fake_arm("a", script), fake_arm("b", script),
                                   fake_arm("c", script)], jobs=1)
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
        Arm(name="strong", agent=AgentSpec(adapter="mock", options={"solve_rate": 1.0,
                                                                     "cost_usd": 0.02})),
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
