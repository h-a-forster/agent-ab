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
from pathlib import Path, PurePath

from .errors import ConfigError, WorkspaceError
from .model import Arm, Command, ProcResult, Task
from .proc import IS_WINDOWS, build_env, run_process

_GIT_TIMEOUT_S = 600.0
_EXCLUDED_DIRS = frozenset({".git"})

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


def _sanitize_label(label: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-.")
    return clean[:60] or "ws"


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _safe_target(root: Path, rel: str, what: str) -> Path:
    """Resolve a workspace-relative path, refusing anything that escapes the workspace."""
    pure = PurePath(rel)
    if not rel or pure.is_absolute() or pure.anchor or ".." in pure.parts:
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


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
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

    ``.git`` directories are skipped. Symlinks are recreated as links (copied as files when the
    platform refuses), and nothing is ever written through a link that leaves ``root``.
    """
    root_resolved = root.resolve()
    if not _is_within(dst.resolve(), root_resolved):
        raise WorkspaceError(f"refusing to write outside the workspace: {dst}")
    dst.mkdir(parents=True, exist_ok=True)
    with os.scandir(src) as entries:
        for entry in entries:
            s = Path(entry.path)
            d = dst / entry.name
            if entry.is_dir(follow_symlinks=False) and entry.name in _EXCLUDED_DIRS:
                continue
            if d.is_symlink() or (d.exists() and d.is_dir() != entry.is_dir(follow_symlinks=False)):
                # Replace whatever is in the way rather than writing through or into it.
                _remove_path(d)
            if entry.is_symlink():
                if d.exists():
                    _remove_path(d)
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


def _run_git(cwd: Path, *args: str, stdout=None) -> subprocess.CompletedProcess:
    git = _git()
    if git is None:
        raise WorkspaceError("git is not available")
    try:
        cp = subprocess.run(
            _git_argv(git, *args),
            cwd=str(cwd),
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
    # An empty template dir keeps host-installed template hooks out of the new repository.
    _run_git(ws, "init", "-q", "--template=")
    _run_git(ws, "add", "-A")
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


def diff_stats(ws: Workspace, patch_path: Path) -> tuple[int, int, int] | None:
    """Write the agent's changes since the baseline to ``patch_path`` and count them.

    Returns ``(files_changed, lines_added, lines_removed)``; binary files count as changed with
    zero lines. Returns None when there is no baseline (git unavailable) or git cannot read the
    workspace any more (e.g. the agent deleted ``.git``), since diff stats are informational.
    Call it before ``install_checks`` so check files do not show up as agent changes.
    """
    if ws.baseline_commit is None or _git() is None:
        return None
    base = ws.baseline_commit
    common = ("--no-renames", "--no-ext-diff", "--no-textconv")
    try:
        _run_git(ws.path, "add", "-A")
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
    """Copy the task's hidden ``checks/`` over the workspace root, overwriting agent files."""
    if task.checks is not None:
        _copy_into(Path(task.checks), ws.path, "checks")


def apply_solution(ws: Workspace, task: Task) -> None:
    """Copy the task's reference ``solution/`` over the workspace (used by validate and mocks)."""
    if task.solution is not None:
        _copy_into(Path(task.solution), ws.path, "solution")


def destroy_workspace(ws: Workspace) -> None:
    """Delete the workspace directory. Retries with backoff and never raises.

    Windows keeps files locked briefly after processes exit and git writes read-only objects,
    so a single ``rmtree`` is not enough; after a few attempts the directory is left behind.
    """
    path = Path(ws.path)
    for attempt in range(6):
        try:
            if not os.path.lexists(path):
                return
            _rmtree(path)
            return
        except Exception:
            time.sleep(min(0.1 * 2**attempt, 2.0))


_PLACEHOLDER = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")


def _expand(template: str, values: Mapping[str, str]) -> str:
    def sub(m: re.Match) -> str:
        token = m.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        name = m.group(1)
        if name not in values:
            raise ConfigError(f"unknown placeholder {{{name}}} in command: {template!r}")
        return values[name]

    return _PLACEHOLDER.sub(sub, template)


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
