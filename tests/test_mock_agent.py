"""Tests for the offline mock agent: determinism, rates, failure modes and usage reporting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_ab import mock_agent
from agent_ab.adapters.command import _read_usage_file
from agent_ab.mock_agent import BROKEN_MARKER, CRASH_EXIT_CODE, INFRA_EXIT_CODE, decide

SRC = str(Path(mock_agent.__file__).resolve().parents[1])


def make_task(tmp_path: Path) -> Path:
    solution = tmp_path / "solution"
    (solution / "pkg").mkdir(parents=True)
    (solution / "pkg" / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    return solution


def run_agent(tmp_path: Path, seed: int, options: dict, *, solution: Path | None,
              task_id: str = "t1") -> tuple[int, Path, Path]:
    root = tmp_path / f"s{seed}"
    ws, art = root / "ws", root / "art"
    ws.mkdir(parents=True)
    (ws / "pkg").mkdir()
    (ws / "pkg" / "mod.py").write_text("def f():\n    return 0\n", encoding="utf-8")
    argv = [sys.executable, "-m", "agent_ab.mock_agent", "--workspace", str(ws),
            "--artifacts", str(art), "--seed", str(seed), "--task-id", task_id,
            "--options", json.dumps(options)]
    if solution is not None:
        argv += ["--solution", str(solution)]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([SRC, os.environ.get("PYTHONPATH", "")])}
    cp = subprocess.run(argv, cwd=ws, env=env, capture_output=True, timeout=60,
                        stdin=subprocess.DEVNULL)
    return cp.returncode, ws, art


def solved(ws: Path) -> bool:
    return "return 1" in (ws / "pkg" / "mod.py").read_text(encoding="utf-8")


def test_decide_is_deterministic():
    opts = {"solve_rate": 0.5, "cost_usd": [0.01, 0.1], "crash_rate": 0.2}
    assert [decide(s, opts) for s in range(50)] == [decide(s, opts) for s in range(50)]
    assert len({decide(s, opts).cost_usd for s in range(50)}) > 1


def test_decide_rates_are_independent():
    # Changing crash_rate must not change which seeds solve.
    a = [decide(s, {"solve_rate": 0.4}).solve for s in range(300)]
    b = [decide(s, {"solve_rate": 0.4, "crash_rate": 0.5}).solve for s in range(300)]
    assert a == b


@pytest.mark.parametrize("rate", [0.0, 0.25, 0.7, 1.0])
def test_decide_solve_rate(rate):
    n = 2000
    hits = sum(decide(s, {"solve_rate": rate}).solve for s in range(n))
    assert abs(hits / n - rate) < 0.04


def test_decide_task_rates_and_ranges():
    opts = {"solve_rate": 0.0, "task_rates": {"easy": 1.0}, "cost_usd": [0.5, 1.5],
            "duration_s": [0.0, 0.0], "tokens": 400}
    for s in range(100):
        d = decide(s, opts, "easy")
        assert d.solve and 0.5 <= d.cost_usd <= 1.5
        assert 300 <= d.input_tokens <= 500 and 1 <= d.turns <= 5
        assert not decide(s, opts, "hard").solve


def test_solve_rate_over_200_seeds():
    opts = {"solve_rate": 0.3}
    hits = sum(decide(s, opts, "t1").solve for s in range(200))
    assert abs(hits / 200 - 0.3) < 0.1


def test_subprocess_matches_decision_seed_by_seed(tmp_path):
    # Process start-up dominates on Windows, so a smaller sample is run for real; exact
    # seed-by-seed agreement with decide() carries the 200-seed rate check over.
    solution = make_task(tmp_path)
    opts = {"solve_rate": 0.3, "cost_usd": [0.01, 0.02]}
    seeds = range(48)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda s: run_agent(tmp_path, s, opts, solution=solution), seeds))
    assert all(code == 0 for code, _, _ in results)
    outcomes = [solved(ws) for _, ws, _ in results]
    assert outcomes == [decide(s, opts, "t1").solve for s in seeds]
    assert 0 < sum(outcomes) < len(outcomes)
    for _, _, art in results:
        u = _read_usage_file(art / "usage.json")
        assert 0.01 <= u.cost_usd <= 0.02 and u.infra_error is None and u.final_message


def test_subprocess_is_deterministic(tmp_path):
    solution = make_task(tmp_path)
    opts = {"solve_rate": 0.5, "cost_usd": [0.0, 1.0], "tokens": 777}
    _, _, art1 = run_agent(tmp_path / "a", 7, opts, solution=solution)
    _, _, art2 = run_agent(tmp_path / "b", 7, opts, solution=solution)
    assert (art1 / "usage.json").read_text() == (art2 / "usage.json").read_text()


def test_fail_mode_revert_and_break(tmp_path):
    solution = make_task(tmp_path)
    code, ws, _ = run_agent(tmp_path / "r", 1, {"solve_rate": 0.0}, solution=solution)
    assert code == 0 and (ws / "pkg" / "mod.py").read_text(encoding="utf-8").endswith("return 0\n")
    code, ws, art = run_agent(tmp_path / "b", 1, {"solve_rate": 0.0, "fail_mode": "break"},
                              solution=solution)
    assert code == 0
    assert (ws / "pkg" / "mod.py").read_text(encoding="utf-8") == BROKEN_MARKER
    assert "pkg/mod.py" in _read_usage_file(art / "usage.json").final_message


def test_no_solution_counts_as_fail(tmp_path):
    code, ws, art = run_agent(tmp_path, 3, {"solve_rate": 1.0}, solution=None)
    assert code == 0 and not solved(ws)
    assert _read_usage_file(art / "usage.json").cost_usd == pytest.approx(0.01)


def test_crash_and_infra_error(tmp_path):
    solution = make_task(tmp_path)
    code, ws, art = run_agent(tmp_path / "c", 5, {"crash_rate": 1.0, "solve_rate": 1.0},
                              solution=solution)
    assert code == CRASH_EXIT_CODE and not solved(ws) and not (art / "usage.json").exists()
    code, ws, art = run_agent(tmp_path / "i", 5, {"infra_error_rate": 1.0, "solve_rate": 1.0},
                              solution=solution)
    assert code == INFRA_EXIT_CODE and not solved(ws)
    assert "simulated" in _read_usage_file(art / "usage.json").infra_error


def test_rejects_bad_options_json(tmp_path):
    with pytest.raises(SystemExit):
        mock_agent.main(["--workspace", str(tmp_path), "--artifacts", str(tmp_path),
                         "--seed", "1", "--options", "[1]"])


def test_in_process_run(tmp_path):
    solution = make_task(tmp_path)
    ws, art = tmp_path / "ws", tmp_path / "art"
    ws.mkdir()
    code = mock_agent.run(workspace=ws, artifacts=art, seed=0, solution=solution,
                          options={"solve_rate": 1.0, "cost_usd": 0.5})
    assert code == 0 and solved(ws)
    assert _read_usage_file(art / "usage.json").cost_usd == 0.5
