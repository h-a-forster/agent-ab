"""Subprocess execution with timeouts, cancellation and whole-tree termination.

Agents are untrusted, long-running and spawn helpers of their own, so every launch gets its own
process group/session and is killed as a tree. Output goes straight to files to keep memory flat
and to avoid pipe deadlocks; launch failures are reported in the result instead of raised.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from .model import ProcResult

IS_WINDOWS = sys.platform == "win32"

_POLL_S = 0.2  # how often the wait loop checks the deadline and the cancel event
_KILL_GRACE_S = 5.0  # POSIX: time between SIGTERM and SIGKILL
_STDIN_JOIN_S = 5.0  # a stuck stdin writer never blocks the caller longer than this


def _pathext() -> list[str]:
    raw = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    return [e.lower() for e in raw.split(os.pathsep) if e]


def resolve_executable(name: str) -> str | None:
    """Return the full path of an executable, or None if it cannot be found.

    Bare names are looked up on PATH. On Windows the PATHEXT extensions are tried as well, so
    tools installed as ``.cmd``/``.bat`` shims (npm, pipx) resolve to a path ``subprocess`` can
    launch from an argv list. Names containing a directory separator are checked as given.
    """
    if not name:
        return None
    has_sep = os.sep in name or (os.altsep is not None and os.altsep in name)
    if has_sep:
        candidates = [name]
        if IS_WINDOWS and Path(name).suffix.lower() not in _pathext():
            candidates += [name + ext for ext in _pathext()]
        for c in candidates:
            if os.path.isfile(c) and (IS_WINDOWS or os.access(c, os.X_OK)):
                return os.path.abspath(c)
        return None
    found = shutil.which(name)
    # An extension-less hit (e.g. the POSIX shell script npm installs next to the .cmd)
    # cannot be launched by CreateProcess; prefer a PATHEXT variant.
    if IS_WINDOWS and (found is None or Path(found).suffix.lower() not in _pathext()):
        for ext in _pathext():
            alt = shutil.which(name + ext)
            if alt:
                return alt
    return found


def build_env(additions: Mapping[str, str] | None) -> dict[str, str]:
    """Return a copy of ``os.environ`` with ``additions`` applied (values coerced to str).

    On Windows environment names are case-insensitive, so an addition replaces any existing
    variable whose name differs only in case instead of creating a duplicate.
    """
    env = dict(os.environ)
    for key, value in (additions or {}).items():
        if IS_WINDOWS:
            for existing in [k for k in env if k.upper() == key.upper() and k != key]:
                del env[existing]
        env[key] = str(value)
    return env


def kill_tree(proc: subprocess.Popen) -> None:
    """Terminate ``proc`` and every process it spawned. Never raises.

    POSIX: SIGTERM to the process group, SIGKILL after a grace period (the group outlives its
    leader, so the SIGKILL is sent even when the leader exits early). Windows: ``taskkill /T /F``
    walks the parent/child tree, which only works while the root is still alive.
    """
    if IS_WINDOWS:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        with contextlib.suppress(OSError):
            proc.kill()
        return
    try:
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = proc.pid  # leader already reaped; the session id still equals its pid
    with contextlib.suppress(OSError):
        os.killpg(pgid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=_KILL_GRACE_S)
    with contextlib.suppress(OSError):
        os.killpg(pgid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def _write_stdin(pipe, data: bytes) -> None:
    # The child may exit or close stdin without reading everything; that is not our error.
    with contextlib.suppress(OSError, ValueError):
        pipe.write(data)
    with contextlib.suppress(OSError, ValueError):
        pipe.close()


def run_process(
    argv: Sequence[str] | str,
    *,
    cwd: Path,
    env: Mapping[str, str] | None,
    timeout_s: float | None,
    stdout_path: Path,
    stderr_path: Path,
    stdin_text: str | None = None,
    shell: bool = False,
    cancel: threading.Event | None = None,
) -> ProcResult:
    """Run a command to completion, a timeout, or cancellation, and describe the outcome.

    ``env`` is the complete environment for the child (``None`` inherits ours; use
    ``build_env`` for additions). A string ``argv`` always runs through the shell; a sequence
    runs through the shell only when ``shell`` is true. stdout/stderr are written to the given
    files; ``stdin_text`` is fed as UTF-8 from a background thread. On timeout or cancel the
    whole process tree is killed and ``exit_code`` is None. Launch failures never raise: they
    return ``exit_code=None`` with ``start_error`` set.
    """
    stdout_path = Path(stdout_path)
    stderr_path = Path(stderr_path)
    start = time.monotonic()

    def failed(message: str) -> ProcResult:
        # Leave the output files behind so callers can always open them.
        for p in (stdout_path, stderr_path):
            with contextlib.suppress(OSError):
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.touch()
        return ProcResult(
            exit_code=None,
            timed_out=False,
            duration_s=time.monotonic() - start,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            start_error=message,
        )

    if isinstance(argv, str):
        shell = True
        command: str | list[str] = argv
    else:
        args = [str(a) for a in argv]
        if not args:
            return failed("empty command")
        if shell:
            command = subprocess.list2cmdline(args) if IS_WINDOWS else shlex.join(args)
        else:
            exe = args[0]
            has_sep = os.sep in exe or (os.altsep is not None and os.altsep in exe)
            if not has_sep:
                resolved = resolve_executable(exe)
                if resolved is None:
                    return failed(f"executable not found: {exe}")
                args[0] = resolved
            command = args

    cwd = Path(cwd)
    if not cwd.is_dir():
        return failed(f"working directory does not exist: {cwd}")

    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(stdout_path, "wb")  # noqa: SIM115 - closed in the finally below
    except OSError as e:
        return failed(f"cannot open output file: {e}")
    try:
        err = open(stderr_path, "wb")  # noqa: SIM115
    except OSError as e:
        out.close()
        return failed(f"cannot open output file: {e}")

    writer: threading.Thread | None = None
    try:
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=dict(env) if env is not None else None,
                stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                shell=shell,
                **kwargs,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            return failed(f"{type(e).__name__}: {e}")

        if stdin_text is not None and proc.stdin is not None:
            writer = threading.Thread(
                target=_write_stdin,
                args=(proc.stdin, stdin_text.encode("utf-8")),
                name="agent-ab-stdin",
                daemon=True,
            )
            writer.start()

        deadline = None if timeout_s is None else start + max(0.0, float(timeout_s))
        timed_out = cancelled = False
        while True:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=_POLL_S)
                break
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            if deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                break

        if timed_out or cancelled:
            kill_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
        duration = time.monotonic() - start
        if writer is not None:
            writer.join(_STDIN_JOIN_S)
        exit_code = None if (timed_out or cancelled) else proc.returncode
        return ProcResult(
            exit_code=exit_code,
            timed_out=timed_out,
            duration_s=duration,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
        )
    finally:
        out.close()
        err.close()
