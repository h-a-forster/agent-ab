from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from agent_ab import workspace as wsmod
from agent_ab.errors import ConfigError, WorkspaceError
from agent_ab.model import AgentSpec, Arm, Task
from agent_ab.proc import IS_WINDOWS
from agent_ab.workspace import (
    Workspace,
    apply_solution,
    create_workspace,
    destroy_workspace,
    diff_stats,
    install_checks,
    run_command,
)

HAS_GIT = shutil.which("git") is not None
needs_git = pytest.mark.skipif(not HAS_GIT, reason="git not installed")


def _write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _task(tmp_path: Path, *, repo=True, checks=False, solution=False) -> Task:
    tdir = tmp_path / "task"
    tdir.mkdir(exist_ok=True)
    return Task(
        id="t1",
        path=tdir,
        prompt="do it",
        check=("{python}", "-c", "pass"),
        repo=tdir / "repo" if repo else None,
        checks=tdir / "checks" if checks else None,
        solution=tdir / "solution" if solution else None,
    )


def _arm(overlay: Path | None = None, remove: tuple[str, ...] = ()) -> Arm:
    return Arm(name="a", agent=AgentSpec(adapter="mock"), overlay=overlay, remove=remove)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "wsroot"
    r.mkdir()
    return r


@pytest.fixture
def repo_task(tmp_path):
    task = _task(tmp_path, checks=True, solution=True)
    _write(task.repo / "main.py", "a = 1\nb = 2\nc = 3\n")
    _write(task.repo / "AGENTS.md", "instructions\n")
    _write(task.repo / ".hidden" / "cfg", "dot\n")
    _write(task.repo / ".env.example", "X=1\n")
    _write(task.repo / "docs" / "old.md", "old\n")
    _write(task.repo / ".git" / "HEAD", "ref: refs/heads/main\n")
    _write(task.repo / "sub" / ".git" / "config", "[core]\n")
    _write(task.repo / "sub" / "keep.txt", "keep\n")
    return task


def test_create_copies_dotfiles_and_excludes_git(tmp_path, root, repo_task):
    with create_workspace(repo_task, _arm(), root=root, label="t1 / ctrl:r0") as ws:
        p = ws.path
        assert p.parent == root.resolve()
        assert p.name.startswith("agent-ab-t1-ctrl-r0-")
        assert (p / "main.py").read_text() == "a = 1\nb = 2\nc = 3\n"
        assert (p / ".hidden" / "cfg").read_text() == "dot\n"
        assert (p / ".env.example").exists()
        assert (p / "sub" / "keep.txt").exists()
        assert not (p / "sub" / ".git").exists()
        # The only .git is our own snapshot repository, not the task's.
        assert not (p / ".git" / "MARKER").exists()
        assert (p / ".git").is_dir() == HAS_GIT
    assert not p.exists()


def test_label_sanitized_and_default_root(tmp_path):
    task = _task(tmp_path, repo=False)
    ws = create_workspace(task, _arm(), root=None, label="../..\\evil name")
    try:
        assert ws.path.is_dir()
        assert ws.path.parent == Path(tempfile.gettempdir()).resolve()
        assert ws.path.name.startswith("agent-ab-evil-name-")
    finally:
        destroy_workspace(ws)


def test_empty_repo_snapshot(tmp_path, root):
    task = _task(tmp_path, repo=False)
    ws = create_workspace(task, _arm(), root=root, label="empty")
    try:
        if HAS_GIT:
            assert ws.baseline_commit and len(ws.baseline_commit) >= 40
            assert diff_stats(ws, tmp_path / "d.patch") == (0, 0, 0)
        else:
            assert ws.baseline_commit is None
    finally:
        destroy_workspace(ws)


def test_remove_then_overlay(tmp_path, root, repo_task):
    overlay = tmp_path / "overlay"
    _write(overlay / "AGENTS.md", "new instructions\n")  # removed first, then re-added
    _write(overlay / "docs" / "new.md", "new\n")  # merges into existing dir
    _write(overlay / "main.py", "overwritten\n")
    _write(overlay / ".claude" / "skills" / "s.md", "skill\n")
    _write(overlay / ".git" / "junk", "x")
    arm = _arm(overlay, remove=("AGENTS.md", "docs/old.md", "does/not/exist", ".hidden"))
    with create_workspace(repo_task, arm, root=root, label="x") as ws:
        p = ws.path
        assert (p / "AGENTS.md").read_text() == "new instructions\n"
        assert not (p / "docs" / "old.md").exists()
        assert (p / "docs" / "new.md").read_text() == "new\n"
        assert (p / "main.py").read_text() == "overwritten\n"
        assert (p / ".claude" / "skills" / "s.md").exists()
        assert not (p / ".hidden").exists()
        assert not (p / ".git" / "junk").exists()
        if HAS_GIT:
            # The overlay is part of the baseline, so it is not counted as an agent change.
            assert diff_stats(ws, tmp_path / "d.patch") == (0, 0, 0)


def test_overlay_file_replaces_dir_and_vice_versa(tmp_path, root, repo_task):
    overlay = tmp_path / "overlay"
    _write(overlay / "docs", "now a file\n")
    _write(overlay / "main.py" / "inner.txt", "now a dir\n")
    with create_workspace(repo_task, _arm(overlay), root=root, label="x") as ws:
        assert (ws.path / "docs").read_text() == "now a file\n"
        assert (ws.path / "main.py" / "inner.txt").read_text() == "now a dir\n"


@pytest.mark.parametrize(
    "bad",
    ["../outside.txt", "a/../../x", "/etc/passwd", "C:\\Windows", "C:x", ".", ""],
)
def test_remove_escape_refused(tmp_path, root, repo_task, bad):
    sentinel = _write(tmp_path / "outside.txt", "safe\n")
    before = set(root.iterdir())
    with pytest.raises(WorkspaceError):
        create_workspace(repo_task, _arm(remove=(bad,)), root=root, label="x")
    assert sentinel.exists()
    assert set(root.iterdir()) == before  # failed workspace cleaned up


def test_remove_through_symlink_refused(tmp_path, root):
    task = _task(tmp_path)
    outside = tmp_path / "outside"
    _write(outside / "victim.txt", "safe\n")
    task.repo.mkdir(parents=True)
    try:
        os.symlink(outside, task.repo / "link", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted")
    with pytest.raises(WorkspaceError):
        create_workspace(task, _arm(remove=("link/victim.txt",)), root=root, label="x")
    assert (outside / "victim.txt").exists()


def test_overlay_does_not_write_through_symlink(tmp_path, root):
    task = _task(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    task.repo.mkdir(parents=True)
    try:
        os.symlink(outside, task.repo / "link", target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted")
    overlay = tmp_path / "overlay"
    _write(overlay / "link" / "planted.txt", "x\n")
    with create_workspace(task, _arm(overlay), root=root, label="x") as ws:
        assert (ws.path / "link" / "planted.txt").exists()
        assert not (ws.path / "link").is_symlink()
    assert not (outside / "planted.txt").exists()


def test_missing_overlay_dir_is_error(tmp_path, root, repo_task):
    with pytest.raises(WorkspaceError):
        create_workspace(repo_task, _arm(tmp_path / "nope"), root=root, label="x")
    assert list(root.iterdir()) == []


@needs_git
def test_diff_stats_add_modify_delete_binary(tmp_path, root, repo_task):
    _write(repo_task.repo / "blob.bin", bytes(range(256)) * 4)
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        p = ws.path
        _write(p / "main.py", "a = 1\nb = 20\nc = 3\nd = 4\n")  # +2 -1
        _write(p / "new.txt", "one\ntwo\nthree\n")  # +3
        (p / "AGENTS.md").unlink()  # -1
        _write(p / "blob.bin", bytes(range(255, -1, -1)) * 4)  # binary: 0/0
        _write(p / "img.dat", b"\x00\x01\x02binary")  # new binary
        patch = tmp_path / "out" / "diff.patch"
        stats = diff_stats(ws, patch)
        assert stats == (5, 5, 2)
        text = patch.read_text(encoding="utf-8", errors="replace")
        assert "new.txt" in text and "GIT binary patch" in text
        # Idempotent: a second call reports the same totals.
        assert diff_stats(ws, patch) == (5, 5, 2)


@needs_git
def test_diff_stats_none_when_git_dir_deleted(tmp_path, root, repo_task):
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        wsmod._rmtree(ws.path / ".git")
        assert diff_stats(ws, tmp_path / "d.patch") is None


def test_diff_stats_none_without_baseline(tmp_path):
    ws = Workspace(path=tmp_path, baseline_commit=None)
    assert diff_stats(ws, tmp_path / "d.patch") is None


def test_create_without_git(tmp_path, root, repo_task, monkeypatch):
    monkeypatch.setattr(wsmod, "_git", lambda: None)
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        assert ws.baseline_commit is None
        assert not (ws.path / ".git").exists()
        assert diff_stats(ws, tmp_path / "d.patch") is None


@needs_git
def test_snapshot_ignores_host_hooks_and_config(tmp_path, root, repo_task, monkeypatch):
    # A broken global config / hook path must not affect snapshots.
    bad = _write(
        tmp_path / "bad.gitconfig", "[commit]\n\tgpgsign = true\n[core]\n\thooksPath = /x\n"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(bad))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "elsewhere"))
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        assert ws.baseline_commit
        assert (ws.path / ".git").is_dir()
    assert not (tmp_path / "elsewhere").exists()


def test_install_checks_overwrites_agent_files(tmp_path, root, repo_task):
    _write(repo_task.checks / "test_hidden.py", "real check\n")
    _write(repo_task.checks / "main.py", "check version\n")
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        _write(ws.path / "test_hidden.py", "agent faked it\n")
        os.chmod(ws.path / "main.py", stat.S_IREAD)  # agent made it read-only
        if HAS_GIT:
            before = diff_stats(ws, tmp_path / "d.patch")
        install_checks(ws, repo_task)
        assert (ws.path / "test_hidden.py").read_text() == "real check\n"
        assert (ws.path / "main.py").read_text() == "check version\n"
        if HAS_GIT:
            assert before == (1, 1, 0)


def test_install_checks_noop_without_checks(tmp_path, root):
    task = _task(tmp_path, repo=False)
    with create_workspace(task, _arm(), root=root, label="x") as ws:
        install_checks(ws, task)
        apply_solution(ws, task)


def test_apply_solution(tmp_path, root, repo_task):
    _write(repo_task.solution / "main.py", "solved\n")
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        apply_solution(ws, repo_task)
        assert (ws.path / "main.py").read_text() == "solved\n"
        assert (ws.path / "AGENTS.md").exists()


def test_destroy_handles_read_only_files(tmp_path, root, repo_task):
    ws = create_workspace(repo_task, _arm(), root=root, label="x")
    ro_dir = ws.path / "ro"
    _write(ro_dir / "f.txt", "x")
    os.chmod(ro_dir / "f.txt", stat.S_IREAD)
    if not IS_WINDOWS:
        os.chmod(ro_dir, stat.S_IREAD | stat.S_IEXEC)
    destroy_workspace(ws)
    assert not ws.path.exists()


def test_destroy_never_raises(tmp_path, monkeypatch):
    destroy_workspace(Workspace(path=tmp_path / "missing"))
    target = tmp_path / "stuck"
    target.mkdir()

    def boom(_path):
        raise PermissionError("locked")

    monkeypatch.setattr(wsmod, "_rmtree", boom)
    monkeypatch.setattr(wsmod.time, "sleep", lambda _s: None)
    destroy_workspace(Workspace(path=target))  # gives up quietly
    assert target.exists()


def test_run_command_argv_placeholders(tmp_path, root, repo_task):
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        code = "import os, sys; print(sys.argv[1]); print(sys.argv[2]); print(os.getcwd())"
        r = run_command(
            ("{python}", "-c", code, "{workspace}", "{{literal}}"),
            ws,
            timeout_s=30,
            stdout_path=tmp_path / "o.txt",
            stderr_path=tmp_path / "e.txt",
        )
        assert r.exit_code == 0, (tmp_path / "e.txt").read_text()
        lines = (tmp_path / "o.txt").read_text().splitlines()
        assert Path(lines[0]) == ws.path
        assert lines[1] == "{literal}"
        assert Path(lines[2]).resolve() == ws.path.resolve()


def test_run_command_shell_placeholders_and_env(tmp_path, root, repo_task):
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        var = "%AGENT_AB_X%" if IS_WINDOWS else "$AGENT_AB_X"
        cmd = '{python} -c "import sys; print(sys.argv[1:])" {workspace} ' + var
        r = run_command(
            cmd,
            ws,
            timeout_s=30,
            stdout_path=tmp_path / "o.txt",
            stderr_path=tmp_path / "e.txt",
            env={"AGENT_AB_X": "hello"},
        )
        assert r.exit_code == 0, (tmp_path / "e.txt").read_text()
        out = (tmp_path / "o.txt").read_text()
        assert "hello" in out
        assert str(ws.path).replace("\\", "\\\\") in out


def test_run_command_shell_literal_braces(tmp_path, root, repo_task):
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        r = run_command(
            '{python} -c "print({{1: 2}})"',
            ws,
            timeout_s=30,
            stdout_path=tmp_path / "o.txt",
            stderr_path=tmp_path / "e.txt",
        )
        assert r.exit_code == 0, (tmp_path / "e.txt").read_text()
        assert (tmp_path / "o.txt").read_text().strip() == "{1: 2}"


def test_run_command_exit_code_and_timeout(tmp_path, root, repo_task):
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        r = run_command(
            ("{python}", "-c", "import sys; sys.exit(7)"),
            ws,
            timeout_s=30,
            stdout_path=tmp_path / "o.txt",
            stderr_path=tmp_path / "e.txt",
        )
        assert r.exit_code == 7
        r = run_command(
            ["{python}", "-c", "import time; time.sleep(30)"],
            ws,
            timeout_s=0.5,
            stdout_path=tmp_path / "o.txt",
            stderr_path=tmp_path / "e.txt",
        )
        assert r.timed_out and r.exit_code is None


def test_run_command_unknown_placeholder(tmp_path):
    ws = Workspace(path=tmp_path)
    with pytest.raises(ConfigError):
        run_command(
            ("{python}", "{nope}"),
            ws,
            timeout_s=5,
            stdout_path=tmp_path / "o",
            stderr_path=tmp_path / "e",
        )


def test_expand_rules():
    vals = {"python": "py", "workspace": "/w"}
    assert wsmod._expand("{python} {{x}} {workspace}", vals) == "py {x} /w"
    assert wsmod._expand("{{{python}}}", vals) == "{py}"
    with pytest.raises(ConfigError):
        wsmod._expand("{prompt}", vals)


def test_sys_executable_used(tmp_path):
    ws = Workspace(path=tmp_path)
    r = run_command(
        ("{python}", "-c", "import sys; print(sys.executable)"),
        ws,
        timeout_s=30,
        stdout_path=tmp_path / "o",
        stderr_path=tmp_path / "e",
    )
    assert r.exit_code == 0
    assert Path((tmp_path / "o").read_text().strip()).samefile(sys.executable)


# --------------------------------------------------------------------------- hostile repos/agents


def _make_link(link: Path, target: Path) -> None:
    """A directory link the way an agent would make one: a junction on Windows."""
    if IS_WINDOWS:
        import subprocess

        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def _git_tree(path: Path) -> list[tuple[str, int]]:
    return sorted((p.relative_to(path).as_posix(), p.stat().st_size)
                  for p in path.rglob("*") if p.is_file())


@needs_git
def test_git_file_in_repo_is_skipped_and_never_followed(tmp_path, root):
    import subprocess

    victim = tmp_path / "victim"
    victim.mkdir()
    subprocess.run(["git", "init", "-q", str(victim)], check=True)
    before = _git_tree(victim / ".git")
    task = _task(tmp_path)
    _write(task.repo / "a.txt", "hello\n")
    _write(task.repo / ".git", f"gitdir: {(victim / '.git').as_posix()}\n")
    _write(task.repo / "nested" / ".git", f"gitdir: {(victim / '.git').as_posix()}\n")
    with create_workspace(task, _arm(), root=root, label="x") as ws:
        assert (ws.path / ".git").is_dir()
        assert not (ws.path / "nested" / ".git").exists()
        _write(ws.path / "a.txt", "changed\n")
        assert diff_stats(ws, tmp_path / "p.patch") == (1, 1, 1)
    assert _git_tree(victim / ".git") == before


@needs_git
def test_snapshot_refuses_existing_git(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="already exists"):
        wsmod._snapshot(tmp_path)


@needs_git
def test_diff_stats_none_when_agent_plants_git_file(tmp_path, root, repo_task):
    import subprocess

    victim = tmp_path / "victim"
    victim.mkdir()
    subprocess.run(["git", "init", "-q", str(victim)], check=True)
    before = _git_tree(victim / ".git")
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        wsmod._rmtree(ws.path / ".git")
        _write(ws.path / ".git", f"gitdir: {(victim / '.git').as_posix()}\n")
        assert diff_stats(ws, tmp_path / "p.patch") is None
    assert _git_tree(victim / ".git") == before


@needs_git
def test_diff_stats_count_gitignored_files(tmp_path, root):
    task = _task(tmp_path)
    _write(task.repo / ".gitignore", "*.log\nbuild/\n")
    _write(task.repo / "old.log", "baseline\n")
    with create_workspace(task, _arm(), root=root, label="x") as ws:
        _write(ws.path / "old.log", "baseline\nmore\n")
        _write(ws.path / "build" / "out.txt", "a\nb\n")
        assert diff_stats(ws, tmp_path / "p.patch") == (2, 3, 0)


def test_install_checks_replaces_links_without_following(tmp_path, root, repo_task):
    _write(repo_task.checks / "sub" / "helper.txt", "hidden\n")
    _write(repo_task.checks / "single.txt", "check file\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    _write(outside / "keep.txt", "untouched\n")
    with create_workspace(repo_task, _arm(), root=root, label="x") as ws:
        wsmod._rmtree(ws.path / "sub")
        _make_link(ws.path / "sub", outside)
        (ws.path / "single.txt").mkdir()  # wrong type where a check file goes
        _write(ws.path / "single.txt" / "x", "agent\n")
        install_checks(ws, repo_task)
        assert not wsmod._is_link(ws.path / "sub")
        assert (ws.path / "sub" / "helper.txt").read_text(encoding="utf-8") == "hidden\n"
        assert (ws.path / "single.txt").read_text(encoding="utf-8") == "check file\n"
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]


def test_destroy_reports_failure_within_budget(tmp_path, monkeypatch):
    target = tmp_path / "stuck"
    target.mkdir()

    def boom(_path):
        raise PermissionError("locked")

    monkeypatch.setattr(wsmod, "_rmtree", boom)
    monkeypatch.setattr(wsmod, "_DESTROY_BUDGET_S", 0.5)
    import time

    start = time.monotonic()
    assert destroy_workspace(Workspace(path=target)) is False
    assert time.monotonic() - start < 3
    monkeypatch.undo()
    assert destroy_workspace(Workspace(path=target)) is True
    assert destroy_workspace(Workspace(path=target)) is True  # already gone


def test_destroy_does_not_follow_links_inside(tmp_path, root):
    outside = tmp_path / "outside"
    _write(outside / "keep.txt", "untouched\n")
    ws_dir = root / "ws"
    ws_dir.mkdir()
    _make_link(ws_dir / "link", outside)
    assert destroy_workspace(Workspace(path=ws_dir)) is True
    assert (outside / "keep.txt").exists()


def test_diff_ignores_interpreter_caches(tmp_path):
    from agent_ab.model import AgentSpec, Arm, Task
    from agent_ab.workspace import create_workspace, destroy_workspace, diff_stats

    task_dir = tmp_path / "task"
    (task_dir / "repo").mkdir(parents=True)
    (task_dir / "repo" / "a.py").write_text("x = 1\n", encoding="utf-8")
    task = Task(id="t", path=task_dir, prompt="p", check="true", repo=task_dir / "repo")
    ws = create_workspace(task, Arm(name="a", agent=AgentSpec(adapter="mock")), root=tmp_path,
                          label="t")
    try:
        if ws.baseline_commit is None:
            return
        (ws.path / "__pycache__").mkdir()
        (ws.path / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"\0")
        (ws.path / ".pytest_cache" / "v").mkdir(parents=True)
        (ws.path / ".pytest_cache" / "v" / "x").write_text("1", encoding="utf-8")
        (ws.path / "a.py").write_text("x = 2\n", encoding="utf-8")
        stats = diff_stats(ws, tmp_path / "diff.patch")
        assert stats is not None and stats[0] == 1
    finally:
        destroy_workspace(ws)


def test_rebaseline_excludes_setup_output_from_the_diff(tmp_path):
    from agent_ab.model import AgentSpec, Arm, Task
    from agent_ab.workspace import create_workspace, destroy_workspace, diff_stats, rebaseline

    task_dir = tmp_path / "task"
    (task_dir / "repo").mkdir(parents=True)
    (task_dir / "repo" / "a.py").write_text("x = 1\n", encoding="utf-8")
    task = Task(id="t", path=task_dir, prompt="p", check="true", repo=task_dir / "repo")
    ws = create_workspace(task, Arm(name="a", agent=AgentSpec(adapter="mock")), root=tmp_path,
                          label="t")
    try:
        if ws.baseline_commit is None:
            return
        (ws.path / "generated.txt").write_text("from setup\n", encoding="utf-8")
        rebaseline(ws)
        assert diff_stats(ws, tmp_path / "d1.patch") == (0, 0, 0)
        (ws.path / "a.py").write_text("x = 2\n", encoding="utf-8")
        assert diff_stats(ws, tmp_path / "d2.patch")[0] == 1
    finally:
        destroy_workspace(ws)
