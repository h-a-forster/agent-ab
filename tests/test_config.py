"""Tests for agent_ab.config: loading, validation, merging, placeholders, fingerprinting."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from agent_ab import adapters
from agent_ab.adapters.base import Adapter
from agent_ab.config import (
    compute_fingerprint,
    expand_placeholders,
    experiment_to_dict,
    load_experiment,
    load_task,
)
from agent_ab.errors import ConfigError
from agent_ab.model import AgentSpec

# --------------------------------------------------------------------------- fixtures


class FakeAdapter(Adapter):
    option_keys = frozenset({"solve_rate", "permission_mode", "nested", "when"})

    def __init__(self, name: str):
        self.name = name

    def validate(self, spec: AgentSpec) -> list[str]:
        problems = super().validate(spec)
        if spec.effort == "bogus":
            problems.append("effort 'bogus' is not supported")
        return problems

    def build(self, ctx):  # pragma: no cover - never launched here
        raise NotImplementedError

    def parse(self, ctx, result):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture(autouse=True)
def fake_adapters(monkeypatch):
    # Real adapter modules are not needed (or may not exist) for config tests.
    for name in ("mock", "command", "claude-code"):
        monkeypatch.setitem(adapters._REGISTRY, name, "unused:Unused")
        monkeypatch.setitem(adapters._INSTANCES, name, FakeAdapter(name))


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8", newline="\n")
    return path


def make_task(root: Path, tid: str, body: str | None = None, *, files: bool = True) -> Path:
    d = root / "tasks" / tid
    if body is None:
        body = f'prompt = "Fix {tid}."\ncheck = ["{{python}}", "-m", "unittest"]\n'
    write(d / "task.toml", body)
    if files:
        write(d / "repo" / "main.py", "x = 1\n")
        write(d / "checks" / "test_main.py", "import main\n")
    return d


BASE = """\
name = "exp"
tasks = ["tasks/*"]
[agent]
adapter = "mock"
[[arms]]
name = "control"
[[arms]]
name = "treat"
"""


@pytest.fixture
def exp_dir(tmp_path: Path) -> Path:
    make_task(tmp_path, "t1")
    make_task(tmp_path, "t2")
    return tmp_path


def write_exp(root: Path, text: str = BASE) -> Path:
    return write(root / "experiment.toml", text)


def load(root: Path, text: str = BASE, **kw):
    return load_experiment(write_exp(root, text), **kw)


def config_error(root: Path, text: str, **kw) -> ConfigError:
    with pytest.raises(ConfigError) as info:
        load(root, text, **kw)
    return info.value


# --------------------------------------------------------------------------- happy path


def test_full_example_loads(exp_dir: Path):
    (exp_dir / "arms" / "no-tests").mkdir(parents=True)
    write(exp_dir / "arms" / "no-tests" / "AGENTS.md", "no tests\n")
    exp = load(
        exp_dir,
        """\
        name = "tests-vs-no-tests"
        description = "demo"
        tasks = ["tasks/*"]
        exclude_tasks = []
        repeats = 3
        jobs = 2
        seed = 7
        budget_usd = 20
        timeout_s = 1800
        check_timeout_s = 600
        max_retries = 2
        timeout_is_failure = true
        baseline = "control"
        keep_workspaces = false
        workspace_root = ""

        [agent]
        adapter = "claude-code"
        model = "sonnet"
        effort = "medium"
        args = ["--a"]
        env = { A = "1", B = "2" }
        command = []
        [agent.options]
        permission_mode = "bypassPermissions"

        [[arms]]
        name = "control"
        description = "Stock setup"

        [[arms]]
        name = "no-tests"
        prompt_prefix = "P"
        prompt_suffix = "Do not write or run tests."
        overlay = "arms/no-tests"
        remove = ["AGENTS.md", "./docs\\\\x.md"]
        [arms.agent]
        model = "opus"
        args = ["--foo"]
        env = { B = "3" }
        [arms.agent.options]
        solve_rate = 0.5
        """,
    )
    assert exp.name == "tests-vs-no-tests"
    assert exp.root == exp_dir.resolve()
    assert exp.config_path.is_absolute()
    assert (exp.repeats, exp.jobs, exp.seed, exp.max_retries) == (3, 2, 7, 2)
    assert exp.budget_usd == 20.0 and isinstance(exp.budget_usd, float)
    assert exp.workspace_root is None
    assert exp.baseline == "control"
    assert [t.id for t in exp.tasks] == ["t1", "t2"]
    control, treat = exp.arms
    assert control.description == "Stock setup"
    assert control.agent == AgentSpec(
        adapter="claude-code", model="sonnet", effort="medium", args=("--a",),
        env={"A": "1", "B": "2"}, command=None, options={"permission_mode": "bypassPermissions"},
    )
    assert treat.agent.model == "opus"
    assert treat.agent.effort == "medium"
    assert treat.agent.args == ("--a", "--foo")
    assert treat.agent.env == {"A": "1", "B": "3"}
    assert treat.agent.options == {"permission_mode": "bypassPermissions", "solve_rate": 0.5}
    assert treat.overlay == (exp_dir / "arms" / "no-tests").resolve()
    assert treat.remove == ("AGENTS.md", "docs/x.md")
    assert treat.prompt_prefix == "P"
    assert len(exp.fingerprint) == 64


def test_defaults(exp_dir: Path):
    exp = load(exp_dir)
    assert (exp.repeats, exp.jobs, exp.seed, exp.max_retries) == (1, 1, 0, 2)
    assert exp.timeout_s == 1800.0 and exp.check_timeout_s == 600.0
    assert exp.budget_usd is None
    assert exp.timeout_is_failure is True and exp.keep_workspaces is False
    assert exp.baseline == "control"


def test_task_fields(exp_dir: Path):
    make_task(
        exp_dir,
        "full",
        """\
        prompt_file = "PROMPT.md"
        check = "{python} -m pytest {{x}}"
        setup = ["{python}", "-m", "pip", "install", "-e", "."]
        timeout_s = 90
        check_timeout_s = 1.5
        tags = ["bugfix", "py"]
        """,
    )
    write(exp_dir / "tasks" / "full" / "PROMPT.md", "\ufeffDo the thing.\n")
    write(exp_dir / "tasks" / "full" / "solution" / "main.py", "x = 2\n")
    task = load_task(exp_dir / "tasks" / "full")
    assert task.id == "full"
    assert task.path == (exp_dir / "tasks" / "full").resolve()
    assert task.prompt == "Do the thing.\n"
    assert task.check == "{python} -m pytest {{x}}"
    assert task.setup == ("{python}", "-m", "pip", "install", "-e", ".")
    assert task.timeout_s == 90.0 and task.check_timeout_s == 1.5
    assert task.tags == ("bugfix", "py")
    assert task.repo == task.path / "repo"
    assert task.checks == task.path / "checks"
    assert task.solution == task.path / "solution"


def test_task_without_optional_dirs(tmp_path: Path):
    d = make_task(tmp_path, "bare", files=False)
    task = load_task(d)
    assert task.repo is None and task.checks is None and task.solution is None
    assert task.setup is None and task.tags == ()
    assert task.check == ("{python}", "-m", "unittest")


def test_tasks_sorted_and_glob_semantics(tmp_path: Path):
    for tid in ("b", "a", "c.2"):
        make_task(tmp_path, tid)
    (tmp_path / "tasks" / "not-a-task").mkdir()  # no task.toml: silently skipped by globs
    make_task(tmp_path / "more", "z")
    exp = load(tmp_path, BASE.replace('["tasks/*"]', '["tasks/*", "more/tasks/z", "tasks/a"]'))
    assert [t.id for t in exp.tasks] == ["a", "b", "c.2", "z"]
    assert all(t.path.is_absolute() for t in exp.tasks)


def test_recursive_glob(tmp_path: Path):
    make_task(tmp_path / "suite" / "x", "deep")
    exp = load(tmp_path, BASE.replace('["tasks/*"]', '["suite/**/tasks/*"]'))
    assert [t.id for t in exp.tasks] == ["deep"]


def test_exclude_tasks(exp_dir: Path):
    make_task(exp_dir, "slow-1")
    exp = load(exp_dir, BASE.replace('tasks = ["tasks/*"]',
                                     'tasks = ["tasks/*"]\nexclude_tasks = ["slow-*", "t2"]'))
    assert [t.id for t in exp.tasks] == ["t1"]


def test_excluded_task_is_not_parsed(exp_dir: Path):
    make_task(exp_dir, "broken", "not = valid = toml")
    exp = load(exp_dir, BASE.replace('tasks = ["tasks/*"]',
                                     'tasks = ["tasks/*"]\nexclude_tasks = ["broken"]'))
    assert [t.id for t in exp.tasks] == ["t1", "t2"]


def test_bom_in_experiment_file(exp_dir: Path):
    path = exp_dir / "experiment.toml"
    path.write_bytes(b"\xef\xbb\xbf" + BASE.encode())
    assert load_experiment(path).name == "exp"


def test_workspace_root_relative_and_absolute(exp_dir: Path, tmp_path_factory):
    exp = load(exp_dir, 'workspace_root = "ws"\n' + BASE)
    assert exp.workspace_root == (exp_dir / "ws").resolve()
    other = tmp_path_factory.mktemp("abs")
    exp = load(exp_dir, f"workspace_root = {json.dumps(str(other))}\n" + BASE)
    assert exp.workspace_root == other.resolve()


def test_string_path_argument(exp_dir: Path):
    write_exp(exp_dir)
    assert load_experiment(str(exp_dir / "experiment.toml")).name == "exp"


# --------------------------------------------------------------------------- merge rules


def test_merge_rules(exp_dir: Path):
    exp = load(
        exp_dir,
        """\
        name = "m"
        tasks = ["tasks/*"]
        [agent]
        adapter = "mock"
        model = "base-model"
        args = ["--x", "1"]
        env = { K1 = "a", K2 = "b" }
        command = ["run", "{prompt_file}"]
        [agent.options]
        solve_rate = 0.1
        nested = { a = 1, b = 2 }

        [[arms]]
        name = "a"

        [[arms]]
        name = "b"
        [arms.agent]
        adapter = "command"
        model = ""
        effort = "high"
        args = ["--y"]
        env = { K2 = "B", K3 = "c" }
        command = ["other", "{workspace}", "{{literal}}"]
        [arms.agent.options]
        nested = { c = 3 }
        """,
    )
    a, b = exp.arms
    assert a.agent.adapter == "mock" and a.agent.model == "base-model"
    assert a.agent.command == ("run", "{prompt_file}")
    assert b.agent.adapter == "command"
    assert b.agent.model is None  # "" clears the inherited default
    assert b.agent.effort == "high"
    assert b.agent.args == ("--x", "1", "--y")
    assert b.agent.env == {"K1": "a", "K2": "B", "K3": "c"}
    assert b.agent.command == ("other", "{workspace}", "{{literal}}")
    # options merge is shallow: nested tables are replaced, not merged
    assert b.agent.options == {"solve_rate": 0.1, "nested": {"c": 3}}
    assert a.agent.options == {"solve_rate": 0.1, "nested": {"a": 1, "b": 2}}


def test_arm_options_are_independent_copies(exp_dir: Path):
    exp = load(exp_dir, BASE.replace('adapter = "mock"',
                                     'adapter = "mock"\noptions = { nested = { a = 1 } }'))
    a, b = exp.arms
    a.agent.options["nested"]["a"] = 99
    assert b.agent.options["nested"]["a"] == 1


def test_adapter_only_in_arms(exp_dir: Path):
    exp = load(
        exp_dir,
        """\
        name = "x"
        tasks = ["tasks/*"]
        [[arms]]
        name = "a"
        agent = { adapter = "mock" }
        [[arms]]
        name = "b"
        agent = { adapter = "command", command = ["x"] }
        """,
    )
    assert [a.agent.adapter for a in exp.arms] == ["mock", "command"]


def test_empty_command_means_unset(exp_dir: Path):
    exp = load(exp_dir, BASE.replace('adapter = "mock"', 'adapter = "mock"\ncommand = []'))
    assert exp.arms[0].agent.command is None


# --------------------------------------------------------------------------- selection


def test_select_arms_keeps_config_order(exp_dir: Path):
    text = BASE + '[[arms]]\nname = "third"\n'
    exp = load(exp_dir, text, select_arms=["third", "control"])
    assert [a.name for a in exp.arms] == ["control", "third"]
    assert exp.baseline == "control"


def test_select_arms_default_baseline_is_first_selected(exp_dir: Path):
    exp = load(exp_dir, select_arms=["treat"])
    assert exp.baseline == "treat"


def test_select_arms_unknown(exp_dir: Path):
    err = config_error(exp_dir, BASE, select_arms=["nope"])
    assert "unknown arm(s) nope" in str(err) and "control, treat" in str(err)


def test_select_arms_empty(exp_dir: Path):
    assert "no arms selected" in str(config_error(exp_dir, BASE, select_arms=[]))


def test_select_arms_must_keep_baseline(exp_dir: Path):
    err = config_error(exp_dir, 'baseline = "control"\n' + BASE, select_arms=["treat"])
    assert err.where == "experiment.toml: baseline"
    assert "excluded by the arm selection" in str(err)


def test_select_tasks(exp_dir: Path):
    make_task(exp_dir, "other")
    exp = load(exp_dir, select_tasks=["t*"])
    assert [t.id for t in exp.tasks] == ["t1", "t2"]
    exp = load(exp_dir, select_tasks=["other", "t2"])
    assert [t.id for t in exp.tasks] == ["other", "t2"]


def test_select_tasks_none_match(exp_dir: Path):
    assert "no tasks match the selection" in str(config_error(exp_dir, BASE, select_tasks=["zz"]))


# --------------------------------------------------------------------------- experiment errors


@pytest.mark.parametrize(
    ("edit", "where", "fragment"),
    [
        (("", "bogus = 1\n"), "experiment.toml: bogus", "unknown key 'bogus'"),
        (("", 'name = "x"\n'), "experiment.toml", "invalid TOML"),
        (('name = "exp"', 'name = "bad name"'), "experiment.toml: name", "invalid experiment"),
        (('name = "exp"', 'name = "-x"'), "experiment.toml: name", "invalid experiment"),
        (('name = "exp"\n', ""), "experiment.toml: name", "missing required key 'name'"),
        (('name = "exp"', "name = 3"), "experiment.toml: name", "expected a string"),
        (("", "repeats = 0\n"), "experiment.toml: repeats", "must be >= 1"),
        (("", "repeats = -2\n"), "experiment.toml: repeats", "must be >= 1"),
        (("", "repeats = true\n"), "experiment.toml: repeats", "expected an integer, got boolean"),
        (("", "repeats = 2.0\n"), "experiment.toml: repeats", "expected an integer, got float"),
        (("", 'repeats = "3"\n'), "experiment.toml: repeats", "expected an integer, got string"),
        (("", "jobs = 0\n"), "experiment.toml: jobs", "must be >= 1"),
        (("", "jobs = false\n"), "experiment.toml: jobs", "got boolean"),
        (("", "seed = 1.5\n"), "experiment.toml: seed", "expected an integer"),
        (("", "max_retries = -1\n"), "experiment.toml: max_retries", "must be >= 0"),
        (("", "budget_usd = 0\n"), "experiment.toml: budget_usd", "must be > 0"),
        (("", "budget_usd = -5\n"), "experiment.toml: budget_usd", "must be > 0"),
        (("", "budget_usd = nan\n"), "experiment.toml: budget_usd", "finite"),
        (("", "timeout_s = inf\n"), "experiment.toml: timeout_s", "finite"),
        (("", "timeout_s = true\n"), "experiment.toml: timeout_s", "expected a number"),
        (("", "check_timeout_s = 0\n"), "experiment.toml: check_timeout_s", "must be > 0"),
        (("", "timeout_is_failure = 1\n"), "experiment.toml: timeout_is_failure",
         "expected true or false"),
        (("", 'keep_workspaces = "no"\n'), "experiment.toml: keep_workspaces", "true or false"),
        (("", "workspace_root = 5\n"), "experiment.toml: workspace_root", "expected a string"),
        (("", "description = []\n"), "experiment.toml: description", "expected a string"),
        (("", 'baseline = "nope"\n'), "experiment.toml: baseline", "is not an arm"),
        (('tasks = ["tasks/*"]', 'tasks = "tasks/*"'), "experiment.toml: tasks",
         "expected an array of strings"),
        (('tasks = ["tasks/*"]', "tasks = []"), "experiment.toml: tasks", "at least one glob"),
        (('tasks = ["tasks/*"]', 'tasks = ["tasks/*", 3]'), "experiment.toml: tasks[1]",
         "expected a string"),
        (('tasks = ["tasks/*"]\n', ""), "experiment.toml: tasks", "missing required key"),
        (('tasks = ["tasks/*"]', 'tasks = ["nothing/*"]'), "experiment.toml: tasks",
         "no task directories matched"),
        (('tasks = ["tasks/*"]', 'tasks = ["tasks/missing"]'), "experiment.toml: tasks[0]",
         "is not a task directory"),
        (('tasks = ["tasks/*"]', 'tasks = ["tasks/*"]\nexclude_tasks = ["*"]'),
         "experiment.toml: exclude_tasks", "every task is excluded"),
        (('[agent]\nadapter = "mock"', "agent = 1"), "experiment.toml: agent",
         "expected a table"),
        (('adapter = "mock"', 'adapter = "mock"\nfoo = 1'), "experiment.toml: agent.foo",
         "unknown key 'foo'"),
        (('adapter = "mock"', 'adapter = "nope"'), "experiment.toml: agent.adapter",
         "unknown adapter 'nope'"),
        (('adapter = "mock"', 'adapter = ""'), "experiment.toml: agent.adapter",
         "must not be empty"),
        (('adapter = "mock"', "adapter = 1"), "experiment.toml: agent.adapter",
         "expected a string"),
        (('adapter = "mock"', 'adapter = "mock"\nargs = "--x"'), "experiment.toml: agent.args",
         "expected an array of strings"),
        (('adapter = "mock"', 'adapter = "mock"\nargs = ["--x", 1]'),
         "experiment.toml: agent.args[1]", "expected a string"),
        (('adapter = "mock"', 'adapter = "mock"\nenv = { X = 1 }'), "experiment.toml: agent.env.X",
         "expected a string"),
        (('adapter = "mock"', 'adapter = "mock"\nenv = ["X"]'), "experiment.toml: agent.env",
         "expected a table"),
        (('adapter = "mock"', 'adapter = "mock"\nenv = { "A=B" = "1" }'),
         "experiment.toml: agent.env.A=B", "invalid environment variable name"),
        (('adapter = "mock"', 'adapter = "mock"\nmodel = 4'), "experiment.toml: agent.model",
         "expected a string"),
        (('adapter = "mock"', 'adapter = "mock"\ncommand = "run it"'),
         "experiment.toml: agent.command", "expected an array of strings"),
        (('adapter = "mock"', 'adapter = "mock"\ncommand = ["x", "{promt}"]'),
         "experiment.toml: agent.command[1]", "unknown placeholder {promt}"),
        (('adapter = "mock"', 'adapter = "mock"\noptions = 3'), "experiment.toml: agent.options",
         "expected a table"),
        (('adapter = "mock"', 'adapter = "mock"\noptions = { solve_rate = nan }'),
         "experiment.toml: agent.options.solve_rate", "finite"),
        (('adapter = "mock"', 'adapter = "mock"\noptions = { nested = [1.0, inf] }'),
         "experiment.toml: agent.options.nested[1]", "finite"),
        (('adapter = "mock"', 'adapter = "mock"\noptions = { unknown_opt = 1 }'),
         "experiment.toml: arms[0].agent", "unknown option 'unknown_opt'"),
        (('adapter = "mock"', 'adapter = "mock"\neffort = "bogus"'),
         "experiment.toml: arms[0].agent", "effort 'bogus' is not supported"),
    ],
)
def test_experiment_errors(exp_dir: Path, edit, where, fragment):
    old, new = edit
    text = BASE.replace(old, new, 1) if old else new + BASE
    err = config_error(exp_dir, text)
    assert err.where == where, str(err)
    assert fragment in str(err)
    assert str(err).startswith(where)


ARM_HEAD = """\
name = "exp"
tasks = ["tasks/*"]
[agent]
adapter = "mock"
[[arms]]
name = "control"
"""


@pytest.mark.parametrize(
    ("arm", "where", "fragment"),
    [
        ('[[arms]]\nname = "control"\n', "arms[1].name", "duplicate arm name 'control'"),
        ('[[arms]]\nname = "bad/name"\n', "arms[1].name", "invalid arm name"),
        ("[[arms]]\ndescription = 'x'\n", "arms[1].name", "missing required key 'name'"),
        ('[[arms]]\nname = "b"\nmodel = "opus"\n', "arms[1].model", "unknown key 'model'"),
        ('[[arms]]\nname = "b"\n[arms.agent]\nmodl = "x"\n', "arms[1].agent.modl",
         "unknown key 'modl'"),
        ('[[arms]]\nname = "b"\n[arms.agent]\nmodel = 1\n', "arms[1].agent.model",
         "expected a string"),
        ('[[arms]]\nname = "b"\n[arms.agent]\nadapter = "zzz"\n', "arms[1].agent.adapter",
         "unknown adapter 'zzz'"),
        ('[[arms]]\nname = "b"\n[arms.agent]\neffort = "bogus"\n', "arms[1].agent",
         "effort 'bogus'"),
        ('[[arms]]\nname = "b"\n[arms.agent.options]\nfoo = 1\n', "arms[1].agent",
         "unknown option 'foo'"),
        ('[[arms]]\nname = "b"\nagent = "mock"\n', "arms[1].agent", "expected a table"),
        ('[[arms]]\nname = "b"\noverlay = "missing"\n', "arms[1].overlay",
         "overlay directory not found"),
        ('[[arms]]\nname = "b"\noverlay = "/abs"\n', "arms[1].overlay", "must be a relative path"),
        ('[[arms]]\nname = "b"\noverlay = "C:\\\\abs"\n', "arms[1].overlay",
         "must be a relative path"),
        ('[[arms]]\nname = "b"\noverlay = "../up"\n', "arms[1].overlay", "must not contain '..'"),
        ('[[arms]]\nname = "b"\noverlay = ""\n', "arms[1].overlay", "must not be empty"),
        ('[[arms]]\nname = "b"\noverlay = 1\n', "arms[1].overlay", "expected a string"),
        ('[[arms]]\nname = "b"\nremove = ["a/../../b"]\n', "arms[1].remove[0]",
         "must not contain '..'"),
        ('[[arms]]\nname = "b"\nremove = ["ok", "/etc"]\n', "arms[1].remove[1]",
         "must be a relative path"),
        ('[[arms]]\nname = "b"\nremove = ["\\\\\\\\server\\\\share"]\n', "arms[1].remove[0]",
         "must be a relative path"),
        ('[[arms]]\nname = "b"\nremove = ["D:x"]\n', "arms[1].remove[0]",
         "must be a relative path"),
        ('[[arms]]\nname = "b"\nremove = ["."]\n', "arms[1].remove[0]", "must name a path"),
        ('[[arms]]\nname = "b"\nremove = "AGENTS.md"\n', "arms[1].remove", "expected an array"),
        ('[[arms]]\nname = "b"\nprompt_suffix = 3\n', "arms[1].prompt_suffix",
         "expected a string"),
    ],
)
def test_arm_errors(exp_dir: Path, arm, where, fragment):
    err = config_error(exp_dir, ARM_HEAD + arm)
    assert err.where == f"experiment.toml: {where}", str(err)
    assert fragment in str(err)


def test_arms_missing_or_wrong_type(exp_dir: Path):
    head = 'name = "e"\ntasks = ["tasks/*"]\n'
    assert config_error(exp_dir, head).where == "experiment.toml: arms"
    err = config_error(exp_dir, head + "arms = []\n")
    assert "at least one arm" in str(err)
    err = config_error(exp_dir, head + "arms = [1]\n")
    assert err.where == "experiment.toml: arms[0]"
    err = config_error(exp_dir, head + 'arms = "x"\n')
    assert "array of tables" in str(err)


def test_adapter_missing_after_merge(exp_dir: Path):
    text = 'name = "e"\ntasks = ["tasks/*"]\n[[arms]]\nname = "a"\nagent = { model = "x" }\n'
    err = config_error(exp_dir, text)
    assert err.where == "experiment.toml: arms[0].agent.adapter"
    assert "no adapter set" in str(err)


def test_unknown_adapter_lists_valid_names(exp_dir: Path):
    err = config_error(exp_dir, BASE.replace('adapter = "mock"', 'adapter = "nope"'))
    assert "claude-code" in str(err) and "mock" in str(err)


def test_adapter_import_failure_is_config_error(exp_dir: Path, monkeypatch):
    monkeypatch.setitem(adapters._REGISTRY, "broken", "agent_ab.no_such_module:X")
    monkeypatch.delitem(adapters._INSTANCES, "broken", raising=False)
    err = config_error(exp_dir, BASE.replace('adapter = "mock"', 'adapter = "broken"'))
    assert "could not be loaded" in str(err)


def test_missing_experiment_file(tmp_path: Path):
    with pytest.raises(ConfigError, match="file not found"):
        load_experiment(tmp_path / "nope.toml")


def test_experiment_path_is_directory(tmp_path: Path):
    with pytest.raises(ConfigError, match="cannot read"):
        load_experiment(tmp_path)


def test_invalid_utf8(tmp_path: Path):
    path = tmp_path / "experiment.toml"
    path.write_bytes(b'name = "\xff"\n')
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_experiment(path)


def test_toml_syntax_error_names_file_and_position(exp_dir: Path):
    err = config_error(exp_dir, BASE + "[[arms]\n")
    assert err.where == "experiment.toml"
    assert "invalid TOML" in str(err) and "line" in str(err)


def test_duplicate_task_ids_from_different_globs(tmp_path: Path):
    make_task(tmp_path, "same")
    make_task(tmp_path / "other", "same")
    err = config_error(tmp_path, BASE.replace('["tasks/*"]', '["tasks/*", "other/tasks/*"]'))
    assert err.where == "experiment.toml: tasks[1]"
    assert "duplicate task id 'same'" in str(err)
    assert "tasks/same" in str(err) and "other/tasks/same" in str(err)


def test_same_task_matched_twice_is_fine(exp_dir: Path):
    exp = load(exp_dir, BASE.replace('["tasks/*"]', '["tasks/*", "tasks/t1"]'))
    assert [t.id for t in exp.tasks] == ["t1", "t2"]


def test_bad_task_dir_name(exp_dir: Path):
    make_task(exp_dir, "has space")
    err = config_error(exp_dir, BASE)
    assert "invalid task id 'has space'" in str(err)


def test_task_error_is_located_in_task_file(exp_dir: Path):
    make_task(exp_dir, "t3", 'prompt = "x"\ncheck = ["a"]\nextra = 1\n')
    err = config_error(exp_dir, BASE)
    assert err.where == "tasks/t3/task.toml: extra"


# --------------------------------------------------------------------------- task errors


@pytest.mark.parametrize(
    ("body", "where", "fragment"),
    [
        ('prompt = "x"\ncheck = ["a"]\nbogus = 1\n', "bogus", "unknown key 'bogus'"),
        ('check = ["a"]\n', None, "missing required key 'prompt'"),
        ('prompt = "x"\n', "check", "missing required key 'check'"),
        ('prompt = "x"\nprompt_file = "P.md"\ncheck = ["a"]\n', None, "not both"),
        ('prompt = "   \\n"\ncheck = ["a"]\n', "prompt", "prompt is empty"),
        ('prompt = 3\ncheck = ["a"]\n', "prompt", "expected a string"),
        ('prompt_file = "missing.md"\ncheck = ["a"]\n', "prompt_file", "file not found"),
        ('prompt_file = "../escape.md"\ncheck = ["a"]\n', "prompt_file",
         "must stay inside the task directory"),
        ('prompt_file = ""\ncheck = ["a"]\n', "prompt_file", "must not be empty"),
        ('prompt_file = "EMPTY.md"\ncheck = ["a"]\n', "prompt_file", "prompt is empty"),
        ('prompt = "x"\ncheck = []\n', "check", "must not be an empty array"),
        ('prompt = "x"\ncheck = ""\n', "check", "must not be empty"),
        ('prompt = "x"\ncheck = 1\n', "check", "a shell string or an array of strings"),
        ('prompt = "x"\ncheck = ["a", 2]\n', "check[1]", "expected a string"),
        ('prompt = "x"\ncheck = ["", "a"]\n', "check[0]", "must not be empty"),
        ('prompt = "x"\ncheck = ["{pyhton}"]\n', "check[0]", "unknown placeholder {pyhton}"),
        ('prompt = "x"\ncheck = "echo {prompt}"\n', "check", "unknown placeholder {prompt}"),
        ('prompt = "x"\ncheck = "find . -exec {} +"\n', "check", "unknown placeholder {}"),
        ('prompt = "x"\ncheck = "echo }"\n', "check", "unmatched '}'"),
        ('prompt = "x"\ncheck = ["a"]\nsetup = ["{x}"]\n', "setup[0]", "unknown placeholder"),
        ('prompt = "x"\ncheck = ["a"]\ntimeout_s = 0\n', "timeout_s", "must be > 0"),
        ('prompt = "x"\ncheck = ["a"]\ntimeout_s = "5"\n', "timeout_s", "expected a number"),
        ('prompt = "x"\ncheck = ["a"]\ncheck_timeout_s = -1\n', "check_timeout_s", "> 0"),
        ('prompt = "x"\ncheck = ["a"]\ncheck_timeout_s = nan\n', "check_timeout_s", "finite"),
        ('prompt = "x"\ncheck = ["a"]\ntags = "a"\n', "tags", "expected an array"),
        ('prompt = "x"\ncheck = ["a"]\ntags = [1]\n', "tags[0]", "expected a string"),
        ('prompt = "x"\ncheck = ["a"\n', None, "invalid TOML"),
    ],
)
def test_task_errors(tmp_path: Path, body, where, fragment):
    d = make_task(tmp_path, "tk", body)
    write(d / "EMPTY.md", "\n\n")
    write(tmp_path / "tasks" / "escape.md", "outside\n")
    with pytest.raises(ConfigError) as info:
        load_task(d)
    expected = "tk/task.toml" + (f": {where}" if where else "")
    assert info.value.where == expected, str(info.value)
    assert fragment in str(info.value)


def test_task_dir_must_be_dir(tmp_path: Path):
    d = make_task(tmp_path, "tk", files=False)
    write(d / "repo", "a file, not a dir\n")
    with pytest.raises(ConfigError, match="'repo' must be a directory"):
        load_task(d)


def test_task_missing_toml(tmp_path: Path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(ConfigError, match="file not found"):
        load_task(tmp_path / "empty")


def test_task_invalid_id(tmp_path: Path):
    d = make_task(tmp_path, ".hidden")
    with pytest.raises(ConfigError, match="invalid task id"):
        load_task(d)


def test_absolute_prompt_file_rejected(tmp_path: Path):
    outside = write(tmp_path / "outside.md", "hi\n")
    d = make_task(tmp_path, "tk", f'prompt_file = {json.dumps(str(outside))}\ncheck = ["a"]\n')
    with pytest.raises(ConfigError, match="must stay inside the task directory"):
        load_task(d)


def test_prompt_file_in_subdir(tmp_path: Path):
    d = make_task(tmp_path, "tk", 'prompt_file = "docs/P.md"\ncheck = ["a"]\n')
    write(d / "docs" / "P.md", "Sub prompt\n")
    assert load_task(d).prompt == "Sub prompt\n"


# --------------------------------------------------------------------------- placeholders


def test_expand_placeholders_basic():
    values = {"python": "/usr/bin/python3", "workspace": "C:\\ws\\1"}
    assert expand_placeholders("{python} -m x {workspace}", values) == (
        "/usr/bin/python3 -m x C:\\ws\\1"
    )
    assert expand_placeholders("no placeholders", values) == "no placeholders"
    assert expand_placeholders("", values) == ""


def test_expand_placeholders_escapes():
    values = {"python": "py"}
    assert expand_placeholders("{{python}}", values) == "{python}"
    assert expand_placeholders("{{{python}}}", values) == "{py}"
    assert expand_placeholders("awk '{{print $1}}'", values) == "awk '{print $1}'"
    assert expand_placeholders("{{}}", values) == "{}"


def test_expand_placeholders_value_not_reexpanded():
    assert expand_placeholders("{a}", {"a": "{b}\\1"}) == "{b}\\1"


@pytest.mark.parametrize("template", ["{nope}", "{}", "{ python }", "x { y", "x } y", "{python"])
def test_expand_placeholders_errors(template):
    with pytest.raises(ConfigError):
        expand_placeholders(template, {"python": "py"})


def test_expand_placeholders_error_lists_known():
    with pytest.raises(ConfigError, match=r"known: \{python\}, \{workspace\}"):
        expand_placeholders("{pyth}", {"python": "p", "workspace": "w"})


def test_command_placeholders_all_accepted(exp_dir: Path):
    names = ["prompt_file", "prompt", "workspace", "artifacts", "model", "effort", "python",
             "seed"]
    cmd = json.dumps(["{" + n + "}" for n in names])
    exp = load(exp_dir, BASE.replace('adapter = "mock"', f'adapter = "command"\ncommand = {cmd}'))
    assert exp.arms[0].agent.command == tuple("{" + n + "}" for n in names)


def test_task_placeholders_expand_to_runtime_values(tmp_path: Path):
    task = load_task(make_task(tmp_path, "tk"))
    argv = [expand_placeholders(a, {"python": sys.executable, "workspace": "w"})
            for a in task.check]
    assert argv[0] == sys.executable


# --------------------------------------------------------------------------- serialisation


def test_experiment_to_dict_is_json_and_relative(exp_dir: Path):
    write(exp_dir / "arms" / "ov" / "f.txt", "x\n")
    text = BASE.replace('name = "treat"', 'name = "treat"\noverlay = "arms/ov"\nremove = ["a"]')
    text = text.replace('adapter = "mock"',
                        'adapter = "mock"\noptions = { when = 2024-01-02, nested = [1, 2] }')
    exp = load(exp_dir, 'workspace_root = "ws"\n' + text)
    d = experiment_to_dict(exp)
    json.dumps(d, allow_nan=False)
    assert d["name"] == "exp"
    assert d["config"] == "experiment.toml"
    assert d["workspace_root"] == "ws"
    assert d["fingerprint"] == exp.fingerprint
    assert [a["name"] for a in d["arms"]] == ["control", "treat"]
    treat = d["arms"][1]
    assert treat["overlay"] == "arms/ov"
    assert treat["remove"] == ["a"]
    assert treat["agent"]["options"] == {"when": "2024-01-02", "nested": [1, 2]}
    assert treat["agent"]["args"] == []
    t1 = d["tasks"][0]
    assert t1["path"] == "tasks/t1"
    assert t1["repo"] == "tasks/t1/repo" and t1["checks"] == "tasks/t1/checks"
    assert t1["solution"] is None
    assert t1["check"] == ["{python}", "-m", "unittest"]


def test_experiment_to_dict_path_outside_root(tmp_path: Path):
    make_task(tmp_path / "shared", "ext")
    exp_root = tmp_path / "exp"
    text = BASE.replace('["tasks/*"]', json.dumps([str(tmp_path / "shared" / "tasks" / "*")]))
    exp = load(exp_root, text)
    d = experiment_to_dict(exp)
    assert d["tasks"][0]["path"] == (tmp_path / "shared" / "tasks" / "ext").resolve().as_posix()
    json.dumps(d)


def test_shell_string_check_in_dict(exp_dir: Path):
    make_task(exp_dir, "sh", 'prompt = "x"\ncheck = "{python} -m pytest -q"\n')
    d = experiment_to_dict(load(exp_dir))
    assert d["tasks"][0]["check"] == "{python} -m pytest -q"


# --------------------------------------------------------------------------- fingerprint


def _fp(root: Path, text: str = BASE) -> str:
    return load(root, text).fingerprint


def test_fingerprint_matches_compute(exp_dir: Path):
    exp = load(exp_dir)
    assert compute_fingerprint(exp) == exp.fingerprint
    assert _fp(exp_dir) == exp.fingerprint  # deterministic across loads


def test_fingerprint_independent_of_location(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "deeper" / "b"
    for root in (a, b):
        make_task(root, "t1")
    assert _fp(a) == _fp(b)


@pytest.mark.parametrize(
    "edit",
    [
        ("", "jobs = 8\n"),
        ("", "budget_usd = 3.5\n"),
        ("", "keep_workspaces = true\n"),
        ("", 'workspace_root = "elsewhere"\n'),
        ("", 'description = "changed"\n'),
        ('name = "control"', 'name = "control"\ndescription = "prose"'),
    ],
)
def test_fingerprint_ignores_volatile_settings(exp_dir: Path, edit):
    base = _fp(exp_dir)
    old, new = edit
    text = BASE.replace(old, new, 1) if old else new + BASE
    assert _fp(exp_dir, text) == base


@pytest.mark.parametrize(
    "edit",
    [
        ("", "repeats = 2\n"),
        ("", "seed = 1\n"),
        ("", "timeout_s = 10\n"),
        ("", "max_retries = 0\n"),
        ('adapter = "mock"', 'adapter = "mock"\nmodel = "opus"'),
        ('adapter = "mock"', 'adapter = "mock"\nargs = ["--x"]'),
        ('adapter = "mock"', 'adapter = "mock"\nenv = { A = "1" }'),
        ('adapter = "mock"', 'adapter = "mock"\noptions = { solve_rate = 0.2 }'),
        ('name = "treat"', 'name = "treat"\nprompt_suffix = "be brief"'),
        ('name = "treat"', 'name = "treat"\nremove = ["AGENTS.md"]'),
        ('name = "treat"', 'name = "renamed"'),
    ],
)
def test_fingerprint_sensitive_to_config(exp_dir: Path, edit):
    base = _fp(exp_dir)
    old, new = edit
    text = BASE.replace(old, new, 1) if old else new + BASE
    assert _fp(exp_dir, text) != base


@pytest.mark.parametrize(
    ("rel", "content"),
    [
        ("tasks/t1/checks/test_main.py", "import main  # changed\n"),
        ("tasks/t1/checks/new_test.py", "\n"),
        ("tasks/t1/repo/main.py", "x = 2\n"),
        ("tasks/t2/task.toml", 'prompt = "Different."\ncheck = ["{python}", "-m", "unittest"]\n'),
        ("tasks/t2/solution/main.py", "x = 3\n"),
    ],
)
def test_fingerprint_sensitive_to_task_files(exp_dir: Path, rel, content):
    base = _fp(exp_dir)
    write(exp_dir / rel, content)
    assert _fp(exp_dir) != base


def test_fingerprint_sensitive_to_prompt_file(tmp_path: Path):
    d = make_task(tmp_path, "t1", 'prompt_file = "P.md"\ncheck = ["a"]\n')
    write(d / "P.md", "one\n")
    base = _fp(tmp_path)
    write(d / "P.md", "two\n")
    assert _fp(tmp_path) != base


def test_fingerprint_sensitive_to_line_endings(exp_dir: Path):
    base = _fp(exp_dir)
    (exp_dir / "tasks" / "t1" / "repo" / "main.py").write_bytes(b"x = 1\r\n")
    assert _fp(exp_dir) != base


def test_fingerprint_sensitive_to_overlay_files(exp_dir: Path):
    write(exp_dir / "arms" / "ov" / "AGENTS.md", "v1\n")
    text = BASE.replace('name = "treat"', 'name = "treat"\noverlay = "arms/ov"')
    base = _fp(exp_dir, text)
    assert base != _fp(exp_dir)
    write(exp_dir / "arms" / "ov" / "AGENTS.md", "v2\n")
    v2 = _fp(exp_dir, text)
    assert v2 != base
    write(exp_dir / "arms" / "ov" / "sub" / "skill.md", "s\n")
    assert _fp(exp_dir, text) != v2


def test_fingerprint_ignores_caches_and_git(exp_dir: Path):
    base = _fp(exp_dir)
    t1 = exp_dir / "tasks" / "t1"
    write(t1 / "repo" / "__pycache__" / "main.cpython-311.pyc", "junk")
    write(t1 / "repo" / "stray.pyc", "junk")
    write(t1 / "repo" / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(t1 / ".git", "gitdir: elsewhere\n")
    write(exp_dir / "runs" / "old" / "run.json", "{}")
    assert _fp(exp_dir) == base


def test_fingerprint_sensitive_to_task_selection(exp_dir: Path):
    assert load(exp_dir, select_tasks=["t1"]).fingerprint != _fp(exp_dir)
