"""Isolated trial workspaces: create, snapshot, diff, install checks, destroy.

A workspace is a fresh temp directory holding a copy of the task repo with the arm's removals
and overlay applied. A private git snapshot taken right after the overlay is the baseline for
measuring what the agent changed. git runs hermetically so host configuration (hooks, signing,
autocrlf, templates) can neither break nor slow the snapshot.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePath, PureWindowsPath

from .config import expand_placeholders as _expand
from .errors import WorkspaceError
from .model import Arm, Command, ProcResult, Task
from .proc import IS_WINDOWS, build_env, run_process

_GIT_TIMEOUT_S = 600.0
# Never copied, whatever its type: a .git *file* (worktree/submodule pointer) would make the
# snapshot commit into the repository it points at.
_EXCLUDED_NAMES = frozenset({".git"})
_DESTROY_BUDGET_S = 5.0  # total time destroy_workspace may spend retrying
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

# Variables a parent git process (e.g. when agent-ab itself runs from a hook) could leak in and
# redirect our commands at a different repository.
_GIT_LEAKY_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES",
)


@dataclass
class Workspace:
    """A trial workspace. Usable as a context manager that destroys it on exit."""

    path: Path
    baseline_commit: str | None = None  # None when git is unavailable

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc: object) -> None:
        destroy_workspace(self)


# --------------------------------------------------------------------------- paths and copying


# Interpreter and tool caches appear whenever an agent runs code; they are not changes it made.
_CACHE_EXCLUDES = tuple(
    f":(exclude,glob)**/{name}"
    for name in ("__pycache__/**", "*.pyc", ".pytest_cache/**", ".mypy_cache/**", ".ruff_cache/**")
)

def _sanitize_label(label: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")
    return clean[:60] or "ws"


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _safe_target(root: Path, rel: str, what: str) -> Path:
    """Resolve a workspace-relative path, refusing anything that escapes the workspace."""
    pure = PurePath(rel)
    win = PureWindowsPath(rel)
    # Apply Windows rules everywhere so a path is refused the same way on every OS.
    if (
        not rel
        or pure.is_absolute()
        or pure.anchor
        or win.drive
        or rel[0] in "/\\"
        or ".." in re.split(r"[\\/]", rel)
    ):
        raise WorkspaceError(f"{what} path must be relative and inside the workspace: {rel!r}")
    target = root / pure
    root_resolved = root.resolve()
    # Resolve the parent only: the final component may itself be a symlink we want to act on.
    parent = target.parent.resolve()
    if not _is_within(parent, root_resolved) or target.name in ("", "."):
        raise WorkspaceError(f"{what} path escapes the workspace: {rel!r}")
    if parent / target.name == root_resolved:
        raise WorkspaceError(f"{what} path refers to the workspace root: {rel!r}")
    return parent / target.name


def _make_writable(path: str | os.PathLike) -> None:
    with contextlib.suppress(OSError):
        os.chmod(path, os.stat(path, follow_symlinks=False).st_mode | stat.S_IWRITE)


def _is_link(path: str | os.PathLike) -> bool:
    """True for symlinks and, on Windows, junctions and other reparse points."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(IS_WINDOWS and getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def _unlink_link(path: Path) -> None:
    # Removes the link itself, never its target. Directory links/junctions on Windows need
    # rmdir when unlink refuses them.
    _make_writable(path)
    try:
        os.unlink(path)
    except (IsADirectoryError, PermissionError):
        os.rmdir(path)


def _remove_path(path: Path) -> None:
    if _is_link(path):
        _unlink_link(path)
    elif path.is_file():
        _make_writable(path)
        path.unlink()
    elif path.is_dir():
        _rmtree(path)


def _rmtree_handler(func: Callable, path: str, _exc: object) -> None:
    # Windows marks git object files read-only; clear the bit (and the parent's) and retry once.
    _make_writable(os.path.dirname(path))
    _make_writable(path)
    func(path)


def _rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_rmtree_handler)
    else:
        shutil.rmtree(path, onerror=_rmtree_handler)


def _merge_copy(src: Path, dst: Path, root: Path) -> None:
    """Copy ``src`` onto ``dst`` recursively: directories merge, files overwrite.

    Entries named ``.git`` are skipped. Symlinks are recreated as links (copied as files when
    the platform refuses). Whatever is in the way at a destination path (a link, junction, or
    an entry of the other type) is removed without following it, so nothing is ever written
    through a link.
    """
    root_resolved = root.resolve()
    if not _is_within(dst.resolve(), root_resolved):
        raise WorkspaceError(f"refusing to write outside the workspace: {dst}")
    dst.mkdir(parents=True, exist_ok=True)
    with os.scandir(src) as entries:
        for entry in entries:
            s = Path(entry.path)
            d = dst / entry.name
            if entry.name in _EXCLUDED_NAMES:
                continue
            src_is_link = _is_link(s)
            if _is_link(d) or (
                os.path.lexists(d) and (src_is_link or d.is_dir() != entry.is_dir())
            ):
                # Replace whatever is in the way rather than writing through or into it.
                _remove_path(d)
            if src_is_link:
                try:
                    os.symlink(os.readlink(s), d, target_is_directory=s.is_dir())
                except OSError:
                    if s.is_file():
                        shutil.copy2(s, d)
                continue
            if entry.is_dir():
                _merge_copy(s, d, root)
                continue
            if d.exists():
                _make_writable(d)
            shutil.copy2(s, d)
    with contextlib.suppress(OSError):
        shutil.copystat(src, dst)
    # A read-only source directory would otherwise lock us out of later overlays and cleanup.
    _make_writable(dst)


def _copy_into(src: Path, ws: Path, what: str) -> None:
    if not src.is_dir():
        raise WorkspaceError(f"{what} directory not found: {src}")
    try:
        _merge_copy(src, ws, ws)
    except WorkspaceError:
        raise
    except (OSError, shutil.Error) as e:
        raise WorkspaceError(f"copying {what} into the workspace failed: {e}") from e


# --------------------------------------------------------------------------- git


_git_lock = threading.Lock()
_git_path: str | None | bool = False  # False = not looked up yet


def _git() -> str | None:
    global _git_path
    with _git_lock:
        if _git_path is False:
            _git_path = shutil.which("git")
        return _git_path  # type: ignore[return-value]


def _git_env() -> dict[str, str]:
    env = build_env(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
    )
    for var in _GIT_LEAKY_VARS:
        env.pop(var, None)
    return env


def _git_argv(git: str, *args: str) -> list[str]:
    return [
        git,
        "-c", "user.name=agent-ab",
        "-c", "user.email=agent-ab@localhost",
        "-c", "commit.gpgsign=false",
        "-c", "core.autocrlf=false",
        "-c", "core.safecrlf=false",
        "-c", "core.fsmonitor=false",
        "-c", "core.longpaths=true",
        "-c", "core.quotepath=false",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "init.defaultBranch=main",
        *args,
    ]  # fmt: skip


def _run_git(ws: Path, *args: str, stdout=None) -> subprocess.CompletedProcess:
    git = _git()
    if git is None:
        raise WorkspaceError("git is not available")
    # Explicit locations: discovery could otherwise climb into an enclosing repository or
    # follow a .git file to someone else's.
    located = (f"--git-dir={ws / '.git'}", f"--work-tree={ws}")
    try:
        cp = subprocess.run(
            _git_argv(git, *located, *args),
            cwd=str(ws),
            env=_git_env(),
            stdin=subprocess.DEVNULL,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise WorkspaceError(f"git {args[0]} failed: {e}") from e
    if cp.returncode != 0:
        tail = (cp.stderr or b"").decode("utf-8", "replace").strip()[-500:]
        raise WorkspaceError(f"git {args[0]} failed (exit {cp.returncode}): {tail}")
    return cp


def _snapshot(ws: Path) -> str:
    if os.path.lexists(ws / ".git"):
        raise WorkspaceError(f"refusing to snapshot: {ws / '.git'} already exists")
    # An empty template dir keeps host-installed template hooks out of the new repository.
    _run_git(ws, "init", "-q", "--template=")
    # --force: files the task's .gitignore matches are still part of the baseline.
    _run_git(ws, "add", "-A", "--force", "--", ".", *_CACHE_EXCLUDES)
    _run_git(ws, "commit", "-q", "--no-verify", "--allow-empty", "-m", "agent-ab baseline")
    out = _run_git(ws, "rev-parse", "HEAD").stdout.decode("ascii", "replace").strip()
    if not out:
        raise WorkspaceError("git rev-parse returned no commit")
    return out


# --------------------------------------------------------------------------- public API


def create_workspace(task: Task, arm: Arm, *, root: Path | None, label: str) -> Workspace:
    """Create an isolated workspace for one attempt and snapshot it with git.

    Copies ``task.repo`` (dotfiles included, ``.git`` excluded), deletes ``arm.remove`` paths,
    copies ``arm.overlay`` on top, then commits everything as the baseline so the agent's diff
    excludes the arm's own files. Raises ``WorkspaceError``; nothing is left behind on failure.
    """
    try:
        if root is not None:
            Path(root).mkdir(parents=True, exist_ok=True)
        path = Path(
            tempfile.mkdtemp(prefix=f"agent-ab-{_sanitize_label(label)}-", dir=root)
        ).resolve()
    except OSError as e:
        raise WorkspaceError(f"cannot create workspace directory: {e}") from e
    ws = Workspace(path=path)
    try:
        if task.repo is not None:
            _copy_into(Path(task.repo), path, "task repo")
        for rel in arm.remove:
            target = _safe_target(path, rel, "remove")
            try:
                _remove_path(target)
            except FileNotFoundError:
                continue  # already absent: removing it is a no-op
            except OSError as e:
                raise WorkspaceError(f"cannot remove {rel!r}: {e}") from e
        if arm.overlay is not None:
            _copy_into(Path(arm.overlay), path, "overlay")
        if _git() is not None:
            ws.baseline_commit = _snapshot(path)
    except BaseException:
        destroy_workspace(ws)
        raise
    return ws


def rebaseline(ws: Workspace) -> None:
    """Commit the workspace as it is now and make that the baseline.

    Called after the task's setup command, so files setup creates (installed packages,
    generated sources) are not counted as the agent's changes. A no-op without git.
    """
    if ws.baseline_commit is None or _git() is None:
        return
    _run_git(ws.path, "add", "-A", "--force", "--", ".", *_CACHE_EXCLUDES)
    _run_git(ws.path, "commit", "-q", "--no-verify", "--allow-empty", "-m", "agent-ab setup")
    out = _run_git(ws.path, "rev-parse", "HEAD").stdout.decode("ascii", "replace").strip()
    if not out:
        raise WorkspaceError("git rev-parse returned no commit")
    ws.baseline_commit = out


def diff_stats(ws: Workspace, patch_path: Path) -> tuple[int, int, int] | None:
    """Write the agent's changes since the baseline to ``patch_path`` and count them.

    Returns ``(files_changed, lines_added, lines_removed)``; binary files count as changed with
    zero lines, and files ignored by the task's .gitignore count too. Returns None when there
    is no baseline (git unavailable) or the workspace's git directory is gone or replaced
    (e.g. the agent deleted ``.git``), since diff stats are informational. Call it before
    ``install_checks`` so check files do not show up as agent changes.
    """
    if ws.baseline_commit is None or _git() is None:
        return None
    git_dir = Path(ws.path) / ".git"
    if _is_link(git_dir) or not git_dir.is_dir():
        return None  # a .git file or link would redirect git into another repository
    base = ws.baseline_commit
    common = ("--no-renames", "--no-ext-diff", "--no-textconv")
    try:
        _run_git(ws.path, "add", "-A", "--force", "--", ".", *_CACHE_EXCLUDES)
        patch_path = Path(patch_path)
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        with open(patch_path, "wb") as fh:
            _run_git(ws.path, "diff", "--cached", "--binary", *common, base, "--", stdout=fh)
        raw = _run_git(ws.path, "diff", "--cached", "--numstat", "-z", *common, base, "--").stdout
    except (WorkspaceError, OSError):
        return None
    files = added = removed = 0
    for record in raw.decode("utf-8", "replace").split("\0"):
        parts = record.split("\t", 2)
        if len(parts) != 3:
            continue
        files += 1
        if parts[0].isdigit():
            added += int(parts[0])
        if parts[1].isdigit():
            removed += int(parts[1])
    return files, added, removed


def install_checks(ws: Workspace, task: Task) -> None:
    """Copy the task's hidden ``checks/`` over the workspace root, overwriting agent files.

    Anything the agent left at a check path (file, directory, symlink, junction) is replaced
    without following links. Raises ``WorkspaceError`` if the workspace cannot take the files.
    """
    if task.checks is not None:
        _copy_into(Path(task.checks), ws.path, "checks")


def apply_solution(ws: Workspace, task: Task) -> None:
    """Copy the task's reference ``solution/`` over the workspace (used by validate and mocks)."""
    if task.solution is not None:
        _copy_into(Path(task.solution), ws.path, "solution")


def destroy_workspace(ws: Workspace) -> bool:
    """Delete the workspace directory; return True once it is gone. Never raises.

    Windows keeps files locked briefly after processes exit and git writes read-only objects,
    so a single ``rmtree`` is not enough. Retries with backoff for about five seconds in total,
    then gives up and leaves the directory behind (False) rather than stalling the run.
    """
    path = Path(ws.path)
    deadline = time.monotonic() + _DESTROY_BUDGET_S
    for attempt in range(12):
        try:
            if not os.path.lexists(path):
                return True
            if _is_link(path):
                _unlink_link(path)
            else:
                _rmtree(path)
            return True
        except Exception:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.1 * 2 ** min(attempt, 4), 1.0, remaining))
    return not os.path.lexists(path)


def _shell_quote(value: str) -> str:
    # Interpreter and workspace paths often contain spaces; quote only when needed so commands
    # that already wrap the placeholder in quotes stay valid for plain paths.
    if IS_WINDOWS:
        return f'"{value}"' if any(c in value for c in " \t&()^|<>,;=") else value
    return shlex.quote(value)


def run_command(
    cmd: Command,
    ws: Workspace,
    *,
    timeout_s: float | None,
    stdout_path: Path,
    stderr_path: Path,
    env: Mapping[str, str] | None = None,
    cancel: threading.Event | None = None,
) -> ProcResult:
    """Run a task command (setup or check) inside the workspace.

    ``{python}`` and ``{workspace}`` expand to the running interpreter and the workspace path
    (``{{``/``}}`` give literal braces). A string runs through the shell, with the expanded
    paths quoted as needed; a tuple/list runs as argv. ``env`` holds additions to the inherited
    environment. Unknown placeholders raise ``ConfigError``.
    """
    values = {"python": sys.executable, "workspace": str(ws.path)}
    full_env = build_env(env)
    if isinstance(cmd, str):
        quoted = {k: _shell_quote(v) for k, v in values.items()}
        return run_process(
            _expand(cmd, quoted),
            cwd=ws.path,
            env=full_env,
            timeout_s=timeout_s,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            shell=True,
            cancel=cancel,
        )
    argv = [_expand(str(part), values) for part in cmd]
    return run_process(
        argv,
        cwd=ws.path,
        env=full_env,
        timeout_s=timeout_s,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        cancel=cancel,
    )
