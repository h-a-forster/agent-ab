import json
from pathlib import Path

import pytest

from agent_ab.errors import RunStoreError
from agent_ab.model import AgentSpec, Arm, Experiment, Task, TrialRecord
from agent_ab.store import TRIALS_FILE, RunStore, is_done


def make_exp(tmp_path: Path, fingerprint: str = "abc", name: str = "exp") -> Experiment:
    task_dir = tmp_path / "tasks" / "t1"
    task_dir.mkdir(parents=True, exist_ok=True)
    task = Task(id="t1", path=task_dir, prompt="do it", check="true")
    spec = AgentSpec(adapter="mock")
    return Experiment(
        name=name,
        config_path=tmp_path / "experiment.toml",
        root=tmp_path,
        tasks=(task,),
        arms=(Arm(name="a", agent=spec), Arm(name="b", agent=spec)),
        baseline="a",
        fingerprint=fingerprint,
    )


def rec(tid: str = "t1__a__r0", attempt: int = 0, status: str = "pass", cost=0.5) -> TrialRecord:
    task, arm, rep = tid.split("__")
    return TrialRecord(
        trial_id=tid, task=task, arm=arm, repeat=int(rep[1:]), attempt=attempt,
        status=status, passed=status == "pass", cost_usd=cost,
    )


def test_create_open_roundtrip(tmp_path):
    exp = make_exp(tmp_path)
    store = RunStore.create(tmp_path / "run", exp, planned_trials=4)
    again = RunStore.open(tmp_path / "run")
    assert again.meta["experiment"] == "exp"
    assert again.meta["planned_trials"] == 4
    assert again.meta["fingerprint"] == "abc"
    assert store.records() == []


def test_create_refuses_existing_run(tmp_path):
    exp = make_exp(tmp_path)
    RunStore.create(tmp_path / "run", exp, 1)
    with pytest.raises(RunStoreError, match="already contains a run"):
        RunStore.create(tmp_path / "run", exp, 1)


def test_open_rejects_non_run_dirs(tmp_path):
    with pytest.raises(RunStoreError, match="not an agent-ab run"):
        RunStore.open(tmp_path)
    (tmp_path / "run.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(RunStoreError, match="cannot read"):
        RunStore.open(tmp_path)
    (tmp_path / "run.json").write_text(json.dumps({"tool": "other"}), encoding="utf-8")
    with pytest.raises(RunStoreError, match="not written by agent-ab"):
        RunStore.open(tmp_path)


def test_open_rejects_newer_schema(tmp_path):
    (tmp_path / "run.json").write_text(json.dumps({"tool": "agent-ab", "schema": 99}), "utf-8")
    with pytest.raises(RunStoreError, match="Upgrade"):
        RunStore.open(tmp_path)


def test_check_compatible(tmp_path):
    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 1)
    store.check_compatible(make_exp(tmp_path))
    with pytest.raises(RunStoreError, match="changed since this run started"):
        store.check_compatible(make_exp(tmp_path, fingerprint="zzz"))
    store.check_compatible(make_exp(tmp_path, fingerprint="zzz"), force=True)
    with pytest.raises(RunStoreError, match="belongs to experiment"):
        store.check_compatible(make_exp(tmp_path, name="other"))


def test_append_and_final_records(tmp_path):
    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 2)
    store.append(rec(attempt=0, status="error", cost=0.1))
    store.append(rec(attempt=1, status="pass", cost=0.4))
    store.append(rec("t1__b__r0", status="fail", cost=None))
    assert len(store.records()) == 3
    final = store.final_records()
    assert final["t1__a__r0"].status == "pass"
    assert final["t1__a__r0"].attempt == 1
    assert final["t1__b__r0"].status == "fail"
    assert store.total_cost() == pytest.approx(0.5)


def test_truncated_last_line_is_tolerated(tmp_path):
    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 2)
    store.append(rec())
    with open(tmp_path / "run" / TRIALS_FILE, "a", encoding="utf-8") as f:
        f.write('{"trial_id": "t1__b__r0", "sta')
    assert [r.trial_id for r in store.records()] == ["t1__a__r0"]


def test_mid_file_corruption_is_an_error(tmp_path):
    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 2)
    path = tmp_path / "run" / TRIALS_FILE
    store.append(rec())
    with open(path, "a", encoding="utf-8") as f:
        f.write("garbage\n")
    store.append(rec("t1__b__r0"))
    with pytest.raises(RunStoreError, match="line 2 is corrupt"):
        store.records()


def test_unknown_record_fields_are_ignored(tmp_path):
    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 1)
    data = rec().to_dict() | {"future_field": 1}
    (tmp_path / "run" / TRIALS_FILE).write_text(json.dumps(data) + "\n", encoding="utf-8")
    assert store.records()[0].trial_id == "t1__a__r0"


def test_concurrent_appends_do_not_interleave(tmp_path):
    import threading

    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 400)

    def worker(arm: str):
        for i in range(100):
            store.append(rec(f"t1__{arm}__r{i}"))

    threads = [threading.Thread(target=worker, args=(a,)) for a in "abcd"]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.records()) == 400


def test_attempt_dir_and_relpath(tmp_path):
    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 1)
    d = store.attempt_dir("t1__a__r0", 2)
    assert d.is_dir()
    assert store.relpath(d) == "trials/t1__a__r0/attempt-2"


def test_update_meta(tmp_path):
    store = RunStore.create(tmp_path / "run", make_exp(tmp_path), 1)
    store.update_meta(planned_trials=9)
    assert RunStore.open(tmp_path / "run").meta["planned_trials"] == 9


def test_is_done():
    assert is_done(rec(status="pass"), 2)
    assert is_done(rec(status="fail"), 2)
    assert not is_done(rec(status="error", attempt=1), 2)
    assert is_done(rec(status="error", attempt=2), 2)


def test_env_values_are_redacted_in_run_json(tmp_path):
    from dataclasses import replace

    exp = make_exp(tmp_path)
    secret = AgentSpec(adapter="mock", env={"API_TOKEN": "s3cret"})
    exp = replace(exp, arms=(Arm(name="a", agent=secret), Arm(name="b", agent=secret)))
    RunStore.create(tmp_path / "run", exp, 1)
    text = (tmp_path / "run" / "run.json").read_text(encoding="utf-8")
    assert "s3cret" not in text
    assert "API_TOKEN" in text
