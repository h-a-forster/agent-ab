"""Isolated trial workspaces: create, snapshot, diff, install checks, destroy.

A workspace is a fresh temp directory holding a copy of the task repo with the arm's removals
and overlay applied. A private git snapshot taken right after the overlay is the baseline for
measuring what the agent changed. git runs hermetically so host configuration (hooks, signing,
autocrlf, templates) can neither break nor slow the snapshot.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
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
from .errors import GitDirAlteredError, WorkspaceError
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
    git_config: bytes | None = None  # .git/config after snapshot/setup, restored before diffs

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
            try:
                ws.git_config = (path / ".git" / "config").read_bytes()
            except OSError as e:
                raise WorkspaceError(f"cannot read the snapshot's git config: {e}") from e
    except BaseException:
        destroy_workspace(ws)
        raise
    return ws


def rebaseline(ws: Workspace) -> None:
    """Commit the workspace as it is now and make that the baseline.

    Called after the task's setup command, so files setup creates (installed packages,
    generated sources) are not counted as the agent's changes. Nested git repositories setup
    created (a cloned dependency) are staged as ordinary files, the same way ``diff_stats``
    records them, so agent edits inside them show up in the diff instead of hiding behind an
    unchanging gitlink. A no-op without git.
    """
    if ws.baseline_commit is None or _git() is None:
        return
    _stage_work_tree(Path(ws.path))
    _run_git(ws.path, "commit", "-q", "--no-verify", "--allow-empty", "-m", "agent-ab setup")
    out = _run_git(ws.path, "rev-parse", "HEAD").stdout.decode("ascii", "replace").strip()
    if not out:
        raise WorkspaceError("git rev-parse returned no commit")
    ws.baseline_commit = out
    try:
        ws.git_config = (Path(ws.path) / ".git" / "config").read_bytes()
    except OSError as e:
        raise WorkspaceError(f"cannot read the workspace's git config: {e}") from e


def _nested_git_entries(root: Path) -> list[Path]:
    """Every ``.git`` entry below ``root`` except its own, without descending into links."""
    found: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as it:
            for entry in it:
                path = Path(entry.path)
                if entry.name == ".git":
                    if current != root:
                        found.append(path)
                    continue
                if not _is_link(path) and entry.is_dir(follow_symlinks=False):
                    stack.append(path)
    return found


@contextlib.contextmanager
def _nested_repos_set_aside(ws: Path):
    """Move nested ``.git`` entries out of the work tree for the duration of the block.

    git records a directory holding a ``.git`` as a gitlink (or refuses it if the nested
    repository has no commit), which would drop its files from the diff. With the metadata
    moved aside, the files are staged as ordinary content. The entries are restored on exit.
    """
    try:
        nested = _nested_git_entries(ws)
    except OSError as e:
        raise WorkspaceError(f"scanning the workspace for nested repositories failed: {e}") from e
    if not nested:
        yield
        return
    holding = Path(tempfile.mkdtemp(prefix=f".{ws.name}-nested-", dir=ws.parent))
    moved: list[tuple[Path, Path]] = []
    try:
        for i, path in enumerate(nested):
            target = holding / str(i)
            try:
                os.replace(path, target)
            except OSError as e:
                rel = path.parent.relative_to(ws).as_posix()
                raise WorkspaceError(
                    f"the nested git repository at {rel}/ could not have its metadata "
                    f"set aside to record its files: {e}"
                ) from e
            moved.append((path, target))
        yield
    finally:
        for path, target in reversed(moved):
            with contextlib.suppress(OSError):
                os.replace(target, path)
        with contextlib.suppress(OSError):
            _rmtree(holding)


def _drop_gitlinks(ws: Path) -> None:
    """Remove submodule (gitlink) entries from the index.

    An agent that stages a nested repository (``git add`` after ``git init`` in a subdirectory,
    or ``git submodule add``) leaves a gitlink in the index, which ``git add -A`` keeps even
    with the nested ``.git`` moved aside. Dropping it lets the directory's files be staged as
    ordinary content. The baseline never holds gitlinks, so nothing of the task's is lost.
    """
    listing = _run_git(ws, "ls-files", "-s", "-z").stdout
    # "<mode> <object> <stage>\t<path>" NUL ...
    paths = [
        record.split(b"\t", 1)[1]
        for record in listing.split(b"\0")
        if record.startswith(b"160000 ") and b"\t" in record
    ]
    if paths:
        _run_git(
            ws, "update-index", "--force-remove", "--",
            *(p.decode("utf-8", "surrogateescape") for p in paths),
        )  # fmt: skip


def _restore_git_config(ws: Path, config: bytes) -> None:
    """Put back the repository config agent-ab recorded, discarding what the agent added.

    ``git add`` runs clean filters named in ``.gitattributes`` with commands taken from the
    repository config, so an agent could otherwise make agent-ab run its code while recording
    the diff, after the agent's own processes were killed. Without the agent's config entries
    the filter driver is undefined and git stages the file as is. Files that would point git at
    other config or attributes (``config.worktree``, ``commondir``, ``info/attributes``) are
    removed; agent-ab's repository never has them.
    """
    git_dir = ws / ".git"
    try:
        for rel in ("config.worktree", "commondir", "config"):
            _remove_path(git_dir / rel)
        info = git_dir / "info"
        if _is_link(info):
            _unlink_link(info)
        else:
            _remove_path(info / "attributes")
        (git_dir / "config").write_bytes(config)
    except OSError as e:
        raise WorkspaceError(f"cannot restore the workspace's git config: {e}") from e


def _stage_work_tree(ws: Path, config: bytes | None = None) -> None:
    """Stage every file of the work tree, nested repositories included, as plain content."""
    if config is not None:
        _restore_git_config(ws, config)
    with _nested_repos_set_aside(ws):
        _drop_gitlinks(ws)
        _run_git(ws, "add", "-A", "--force", "--", ".", *_CACHE_EXCLUDES)


def diff_stats(ws: Workspace, patch_path: Path) -> tuple[int, int, int] | None:
    """Write the agent's changes since the baseline to ``patch_path`` and count them.

    Returns ``(files_changed, lines_added, lines_removed)``; binary files count as changed with
    zero lines, and files ignored by the task's .gitignore count too. Files inside a nested git
    repository the agent created (``git clone``, ``git init`` in a subdirectory) are recorded as
    ordinary files; the nested ``.git`` metadata is not, and gitlink entries the agent staged
    for them are dropped from the index. A stale ``.git/index.lock`` (left by a git command
    killed with the agent) is removed first, and the repository config is reset to the one
    recorded after the snapshot (and setup), so filter drivers the agent configured do not
    run. Call it before ``install_checks`` so
    check files do not show up as agent changes.

    Returns None only when there is no baseline (git unavailable). Raises
    ``GitDirAlteredError`` when the workspace's ``.git`` is gone or replaced (for example the
    agent deleted it), ``WorkspaceError`` when git cannot record the changes, and ``OSError``
    when ``patch_path`` cannot be written.
    """
    if ws.baseline_commit is None or _git() is None:
        return None
    git_dir = Path(ws.path) / ".git"
    if _is_link(git_dir) or not git_dir.is_dir():
        # A .git file or link would redirect git into another repository.
        raise GitDirAlteredError("the workspace's .git directory is missing or was replaced")
    base = ws.baseline_commit
    common = ("--no-renames", "--no-ext-diff", "--no-textconv")
    lock = git_dir / "index.lock"
    if os.path.lexists(lock) and not _is_link(lock) and lock.is_file():
        # The agent's processes are gone by now, so any lock is stale.
        with contextlib.suppress(OSError):
            lock.unlink()
    patch_path = Path(patch_path)
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    _stage_work_tree(Path(ws.path), config=ws.git_config)
    raw_entries = _run_git(ws.path, "diff", "--cached", "--raw", "-z", *common, base, "--").stdout
    # -z --raw without renames: ":<old mode> <new mode> <old> <new> <status>" NUL "<path>" NUL.
    fields = raw_entries.split(b"\0")
    for meta, path in zip(fields[0::2], fields[1::2], strict=False):
        modes = meta.lstrip(b":").split(b" ")[:2]
        if b"160000" in modes:
            raise WorkspaceError(
                f"the agent's changes include a git submodule entry at "
                f"{path.decode('utf-8', 'replace')}, whose contents cannot be recorded"
            )
    with open(patch_path, "wb") as fh:
        _run_git(ws.path, "diff", "--cached", "--binary", *common, base, "--", stdout=fh)
    raw = _run_git(ws.path, "diff", "--cached", "--numstat", "-z", *common, base, "--").stdout
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


def apply_patch(ws: Workspace, patch_path: Path) -> None:
    """Apply a patch written by ``diff_stats`` to a fresh workspace.

    Used to grade in a clean copy: the agent's recorded changes go onto a new workspace built
    from the pristine task, so nothing outside that diff (interpreter caches, files written
    after the diff, the agent's ``.git``) reaches the checks. git refuses paths outside the
    work tree and writes through symlinks. An empty patch is a no-op. Raises
    ``WorkspaceError`` if the patch does not apply.
    """
    patch_path = Path(patch_path)
    try:
        if patch_path.stat().st_size == 0:
            return
    except OSError as e:
        raise WorkspaceError(f"cannot read the agent's diff: {e}") from e
    _run_git(ws.path, "apply", "--binary", "--whitespace=nowarn", str(patch_path.resolve()))


def install_checks(ws: Workspace, task: Task) -> None:
    """Copy the task's hidden ``checks/`` over the workspace root, overwriting agent files.

    First, every top-level entry of ``checks/`` that is absent from the pristine ``repo/`` is
    removed from the workspace (links are unlinked, never followed), so files the agent planted
    in check-only paths (say ``checks/test_x.py``) cannot run with the checks. Entries that also
    exist in ``repo/`` keep the merge behaviour: directories merge, files overwrite. Anything the
    agent left at a check path (file, directory, symlink, junction) is replaced without
    following links. Raises ``WorkspaceError`` if the workspace cannot take the files.
    """
    if task.checks is None:
        return
    checks = Path(task.checks)
    if not checks.is_dir():
        raise WorkspaceError(f"checks directory not found: {checks}")
    try:
        for entry in os.scandir(checks):
            if entry.name in _EXCLUDED_NAMES:
                continue
            if task.repo is not None and os.path.lexists(Path(task.repo) / entry.name):
                continue
            _remove_path(ws.path / entry.name)
    except OSError as e:
        raise WorkspaceError(f"clearing check paths in the workspace failed: {e}") from e
    _copy_into(checks, ws.path, "checks")


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


# PYTHONSAFEPATH (Python 3.11+, same as -P) stops `-m` and script runs from putting the workspace
# first on sys.path, where an agent-written `unittest/` package would shadow the stdlib.
CHECK_ENV = {"PYTHONSAFEPATH": "1"}

# Argv checks that start like this run under agent-ab's verifying unittest runner.
_UNITTEST_PREFIX = ("{python}", "-m", "unittest")
_VERIFYING_MODULE = "agent_ab.checkrun"


@dataclass
class CheckResult:
    """Outcome of a check command.

    ``verified`` is True when the check ran under the verifying runner (see
    ``agent_ab.checkrun``); then ``report`` holds the counts it recorded, if any. ``problem``
    explains why a zero exit status is not accepted as a pass.
    """

    proc: ProcResult
    verified: bool = False
    report: dict | None = None
    problem: str | None = None

    @property
    def passed(self) -> bool:
        return self.proc.exit_code == 0 and self.problem is None


def uses_verifying_runner(cmd: Command) -> bool:
    """True for argv checks of the form ``{python} -m unittest ...``."""
    if isinstance(cmd, str):
        return False
    return tuple(str(part) for part in cmd[:3]) == _UNITTEST_PREFIX


def _read_report(path: Path, nonce: str) -> tuple[dict | None, str | None]:
    """Load the verifying runner's report; return ``(report, problem)``."""
    from .checkrun import REPORT_MAX_BYTES

    try:
        with open(path, "rb") as fh:
            raw = fh.read(REPORT_MAX_BYTES + 1)
    except FileNotFoundError:
        return None, "the check exited 0 without recording a result (the process was cut short)"
    except OSError as e:
        return None, f"the check result could not be read: {e}"
    if len(raw) > REPORT_MAX_BYTES:
        return None, "the check result is too large"
    try:
        report = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "the check result is not valid JSON"
    if not isinstance(report, dict) or report.get("nonce") != nonce:
        return None, "the check result does not come from this check run"
    report.pop("nonce", None)
    if report.get("ok") is not True:
        counts = ", ".join(
            f"{k}={report[k]}"
            for k in ("tests_run", "failures", "errors", "skipped", "unexpected_successes")
            if k in report
        )
        return report, f"the check exited 0 but its tests did not pass ({counts})"
    return report, None


def run_check(
    cmd: Command,
    ws: Workspace,
    *,
    timeout_s: float | None,
    stdout_path: Path,
    stderr_path: Path,
    report_path: Path | None = None,
    cancel: threading.Event | None = None,
) -> CheckResult:
    """Run a task's check command in the workspace with the hardened ``CHECK_ENV``.

    An argv check of the form ``{python} -m unittest ...`` runs under the verifying runner
    instead, which records its outcome out of band at ``report_path`` (default: next to
    ``stdout_path``) with a one-time nonce. A zero exit status then counts only when that
    record exists, carries the nonce and shows a clean run, so agent code that forces the exit
    status (``atexit`` hooks, ``os._exit``) cannot fake a pass.
    """
    kw = {"timeout_s": timeout_s, "stdout_path": stdout_path, "stderr_path": stderr_path}
    if not uses_verifying_runner(cmd):
        proc = run_command(cmd, ws, env=CHECK_ENV, cancel=cancel, **kw)
        return CheckResult(proc=proc)

    from .checkrun import NONCE_ENV, REPORT_ENV

    if report_path is None:
        report_path = Path(stdout_path).with_name("check-report.json")
    report_path = Path(report_path).resolve()  # the check runs with cwd=workspace
    with contextlib.suppress(FileNotFoundError):
        report_path.unlink()
    nonce = secrets.token_hex(16)
    env = {**CHECK_ENV, REPORT_ENV: str(report_path), NONCE_ENV: nonce}
    argv = [cmd[0], "-m", _VERIFYING_MODULE, *cmd[3:]]
    proc = run_command(argv, ws, env=env, cancel=cancel, **kw)
    result = CheckResult(proc=proc, verified=True)
    if proc.exit_code == 0:
        result.report, result.problem = _read_report(report_path, nonce)
    return result
