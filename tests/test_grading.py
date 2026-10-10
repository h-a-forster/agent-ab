"""Grading integrity: an agent must not be able to fake a passing check from the workspace."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_runner import fake_arm, make_exp

from agent_ab import adapters
from agent_ab.model import Task
from agent_ab.runner import run_experiment
from agent_ab.store import RunStore

CHECK = ("{python}", "-m", "unittest", "discover", "-s", "checks", "-t", ".")
GOOD = "open('answer.py', 'w').write('VALUE = 2\\n')"
BAD = "open('answer.py', 'w').write('VALUE = 1\\n')"
SHADOW = (
    "import os; os.makedirs('unittest', exist_ok=True)\n"
    "open('unittest/__init__.py', 'w').write('')\n"
    "open('unittest/__main__.py', 'w').write('raise SystemExit(0)\\n')"
)
EXIT_FILE = (
    "import os; os.makedirs('checks', exist_ok=True)\n"
    "open('checks/test_aaa.py', 'w').write('import os; os._exit(0)\\n')"
)


@pytest.fixture(autouse=True)
def _fake_adapter(monkeypatch):
    from test_runner import FakeAdapter

    monkeypatch.setitem(adapters._REGISTRY, "fake", "unused:Unused")
    monkeypatch.setitem(adapters._INSTANCES, "fake", FakeAdapter())


def _task(tmp_path: Path) -> Task:
    tdir = tmp_path / "tasks" / "t1"
    repo, hidden = tdir / "repo", tdir / "checks"
    checks = hidden / "checks"
    repo.mkdir(parents=True)
    checks.mkdir(parents=True)
    (repo / "answer.py").write_text("VALUE = 0\n", encoding="utf-8")
    (checks / "__init__.py").write_text("", encoding="utf-8")
    (checks / "test_answer.py").write_text(
        "import unittest\nimport answer\n\n\nclass T(unittest.TestCase):\n"
        "    def test_value(self):\n        self.assertEqual(answer.VALUE, 2)\n",
        encoding="utf-8",
    )
    return Task(id="t1", path=tdir, prompt="Set VALUE to 2.", check=CHECK, repo=repo, checks=hidden)


def _grade(tmp_path: Path, script: str):
    exp = make_exp(tmp_path, arms=[fake_arm("a", script)], tasks=[_task(tmp_path)])
    run_experiment(exp, tmp_path / "run")
    return RunStore.open(tmp_path / "run").final_records()["t1__a__r0"]


def test_correct_solution_passes(tmp_path):
    rec = _grade(tmp_path, GOOD)
    assert rec.status == "pass" and rec.passed is True


def test_wrong_solution_fails(tmp_path):
    assert _grade(tmp_path, BAD).status == "fail"


def test_unittest_shadow_package_cannot_fake_a_pass(tmp_path):
    rec = _grade(tmp_path, BAD + "\n" + SHADOW)
    assert rec.status == "fail" and rec.passed is False


def test_planted_check_file_cannot_fake_a_pass(tmp_path):
    rec = _grade(tmp_path, BAD + "\n" + EXIT_FILE)
    assert rec.status == "fail" and rec.passed is False


def test_planted_files_do_not_break_a_correct_solution(tmp_path):
    rec = _grade(tmp_path, GOOD + "\n" + SHADOW + "\n" + EXIT_FILE)
    assert rec.status == "pass"


def test_shadow_package_would_win_without_safe_path(tmp_path, monkeypatch):
    # Guards the test above: with the hardening off, the exploit really does fake a pass.
    from agent_ab import workspace

    monkeypatch.setattr(workspace, "CHECK_ENV", {})
    assert _grade(tmp_path, BAD + "\n" + SHADOW).status == "pass"
