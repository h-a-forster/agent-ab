"""Grading integrity: an agent must not be able to fake a passing check from the workspace."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_runner import fake_arm, make_exp

from agent_ab import adapters
from agent_ab.model import AgentSpec, Arm, Task
from agent_ab.runner import run_experiment
from agent_ab.store import RunStore
from agent_ab.workspace import create_workspace, install_checks, run_check

HAS_GIT = shutil.which("git") is not None
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
    monkeypatch.setattr(workspace, "uses_verifying_runner", lambda cmd: False)
    assert _grade(tmp_path, BAD + "\n" + SHADOW).status == "pass"


# Agent code that the checks import and that forces the check's exit status.
ATEXIT = (
    "open('answer.py', 'w').write("
    "'import atexit, os\\natexit.register(os._exit, 0)\\nVALUE = 1\\n')"
)
IMPORT_EXIT = "open('answer.py', 'w').write('import os\\nos._exit(0)\\n')"
IMPORT_SYS_EXIT = "open('answer.py', 'w').write('raise SystemExit(0)\\n')"
IMPORT_SKIP = "open('answer.py', 'w').write('import unittest\\nraise unittest.SkipTest(\"x\")\\n')"
# A stale bytecode file that Python loads without looking at the source (unchecked hash), so
# the module that runs differs from the source in the agent's diff.
FORGED_PYC = (
    "import importlib.util, py_compile\n"
    "open('answer.py', 'w').write('VALUE = 2\\n')\n"
    "py_compile.compile('answer.py', importlib.util.cache_from_source('answer.py'),\n"
    "                   invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)\n"
    "open('answer.py', 'w').write('VALUE = 1\\n')\n"
)


# Regression cases. Only some of them need the verifying runner: with this discovery-style check,
# unittest's loader already reports `raise SystemExit(0)` at import as an error.
@pytest.mark.parametrize(
    "script",
    [ATEXIT, IMPORT_EXIT, IMPORT_SYS_EXIT, IMPORT_SKIP],
    ids=["atexit", "import-os-exit", "import-sys-exit", "import-skip"],
)
def test_forced_exit_status_cannot_fake_a_pass(tmp_path, script):
    rec = _grade(tmp_path, script)
    assert rec.status == "fail" and rec.passed is False


def test_atexit_hook_fails_with_its_own_reason(tmp_path):
    rec = _grade(tmp_path, ATEXIT)
    assert rec.check_exit_code == 0  # the hook did force the exit status
    assert "did not pass" in rec.error and "failures=1" in rec.error


def test_atexit_hook_would_win_without_the_verifying_runner(tmp_path, monkeypatch):
    # Guards the tests above: judged by exit status alone, the hook really does fake a pass.
    from agent_ab import workspace

    monkeypatch.setattr(workspace, "uses_verifying_runner", lambda cmd: False)
    assert _grade(tmp_path, ATEXIT).status == "pass"


def test_check_report_is_saved(tmp_path):
    rec = _grade(tmp_path, GOOD)
    report = json.loads((tmp_path / "run" / rec.artifacts / "check-report.json").read_text())
    assert report["ok"] is True and report["tests_run"] == 1


@pytest.mark.skipif(not HAS_GIT, reason="grading in a clean copy needs git")
def test_forged_bytecode_cannot_fake_a_pass(tmp_path):
    rec = _grade(tmp_path, FORGED_PYC)
    assert rec.status == "fail" and rec.passed is False


@pytest.mark.skipif(not HAS_GIT, reason="grading in a clean copy needs git")
def test_forged_bytecode_would_win_in_place(tmp_path):
    # Guards the test above: graded in the agent's own workspace, the stale bytecode wins.
    task = _task(tmp_path)
    arm = Arm(name="a", agent=AgentSpec(adapter="mock"))
    with create_workspace(task, arm, root=tmp_path / "ws", label="x") as ws:
        subprocess.run([sys.executable, "-c", FORGED_PYC], cwd=ws.path, check=True)
        install_checks(ws, task)
        out = tmp_path / "out"
        out.mkdir()
        kw = {"timeout_s": 60, "stdout_path": out / "o", "stderr_path": out / "e"}
        assert run_check(CHECK, ws, **kw).passed


@pytest.mark.skipif(not HAS_GIT, reason="grading in a clean copy needs git")
def test_files_outside_the_diff_do_not_reach_the_checks(tmp_path):
    # Interpreter caches are not part of the recorded diff, so the clean copy never has them.
    script = (
        GOOD
        + "\nimport os; os.makedirs('__pycache__', exist_ok=True)\n"
        + ("open('__pycache__/marker.txt', 'w').write('x')\n")
    )
    rec = _grade(tmp_path, script)
    assert rec.status == "pass"
    assert "__pycache__" not in (tmp_path / "run" / rec.artifacts / "diff.patch").read_text()


def test_relative_report_path_is_resolved_against_the_caller(tmp_path, monkeypatch):
    # The check runs with the workspace as its cwd; a relative report path must still land
    # where the caller reads it.
    task = _task(tmp_path)
    arm = Arm(name="a", agent=AgentSpec(adapter="mock"))
    with create_workspace(task, arm, root=tmp_path / "ws", label="x") as ws:
        subprocess.run([sys.executable, "-c", GOOD], cwd=ws.path, check=True)
        install_checks(ws, task)
        out = tmp_path / "out"
        out.mkdir()
        monkeypatch.chdir(tmp_path)
        kw = {"timeout_s": 60, "stdout_path": Path("out/o"), "stderr_path": Path("out/e")}
        result = run_check(CHECK, ws, **kw)
        assert result.passed, result.problem
        assert (out / "check-report.json").is_file()
