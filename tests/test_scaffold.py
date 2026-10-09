import tomllib

import pytest

from agent_ab.config import load_experiment
from agent_ab.scaffold import ScaffoldError, init_project, scaffold_files


def test_scaffold_files_layout():
    files = scaffold_files()
    for rel in ("experiment.toml", "experiment.claude-code.toml", "arms/with-guide/AGENTS.md",
                ".gitignore", "README.md"):
        assert rel in files
    tasks = {rel.split("/")[1] for rel in files if rel.startswith("tasks/")}
    assert len(tasks) == 4
    for task in tasks:
        for rel in ("task.toml", "checks/checks/__init__.py"):
            assert f"tasks/{task}/{rel}" in files
        assert any(r.startswith(f"tasks/{task}/repo/") for r in files)
        assert any(r.startswith(f"tasks/{task}/solution/") for r in files)
        assert any(r.startswith(f"tasks/{task}/checks/checks/test_") for r in files)
    assert "runs/" in files[".gitignore"].splitlines()
    # Output and templates stay ASCII so they survive any console or editor encoding.
    for rel, text in files.items():
        assert text.isascii(), rel


def test_templates_are_valid_toml_and_load(tmp_path):
    init_project(tmp_path / "demo")
    demo = load_experiment(tmp_path / "demo" / "experiment.toml")
    assert demo.arms[0].agent.adapter == "mock"
    assert [a.name for a in demo.arms] == ["control", "with-guide"]
    assert demo.repeats == 3 and demo.jobs == 4 and len(demo.tasks) == 4
    assert demo.arms[1].overlay is not None and (demo.arms[1].overlay / "AGENTS.md").is_file()

    claude = load_experiment(tmp_path / "demo" / "experiment.claude-code.toml")
    assert {a.agent.adapter for a in claude.arms} == {"claude-code"}
    text = (tmp_path / "demo" / "experiment.claude-code.toml").read_text(encoding="utf-8")
    assert "WARNING" in text and "sandbox" in text
    tomllib.loads(text)


def test_task_check_command_is_portable(tmp_path):
    init_project(tmp_path)
    demo = load_experiment(tmp_path / "experiment.toml")
    for task in demo.tasks:
        assert task.check == (
            "{python}", "-m", "unittest", "discover", "-s", "checks", "-t", "."
        )
        assert task.solution is not None and task.checks is not None


def test_refuses_non_empty_dir(tmp_path):
    (tmp_path / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ScaffoldError, match="not empty"):
        init_project(tmp_path)
    assert not (tmp_path / "experiment.toml").exists()


def test_force_writes_but_never_deletes(tmp_path):
    (tmp_path / "keep.txt").write_text("mine", encoding="utf-8")
    (tmp_path / "experiment.toml").write_text("old", encoding="utf-8")
    written = init_project(tmp_path, force=True)
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert "mock" in (tmp_path / "experiment.toml").read_text(encoding="utf-8")
    assert len(written) == len(scaffold_files())


def test_refuses_file_target(tmp_path):
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ScaffoldError, match="not a directory"):
        init_project(target, force=True)


def test_creates_missing_parents(tmp_path):
    init_project(tmp_path / "a" / "b")
    assert (tmp_path / "a" / "b" / "experiment.toml").is_file()
