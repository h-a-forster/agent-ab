"""Subprocess execution with timeouts, cancellation and whole-tree termination.

Agents are untrusted, long-running and spawn helpers of their own, so every launch gets its own
process group/session and is killed as a tree. Output goes straight to files to keep memory flat
and to avoid pipe deadlocks; launch failures are reported in the result instead of raised.

Leftover processes are always killed, including after a normal exit: a background helper the
agent forgot (a dev server, a watcher) would otherwise hold workspace files open, keep running
unbilled work and outlive the run. On Windows each launch is placed in a Job Object that is
terminated when the command finishes and that the OS kills when agent-ab itself dies. On POSIX
the command's session process group is killed; a descendant that started its own session
escapes, as does anything a launched process hands to a service manager.
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


class _Job:
    """A Windows Job Object that kills every process in it when terminated or closed.

    The process is assigned right after ``Popen`` returns, so a child it spawns in the first
    instant (before the assignment) is not in the job; real agents need far longer than that to
    start anything, and ``taskkill /T`` still covers that case on timeout and cancel.
    """

    def __init__(self, handle: int):
        self._handle: int | None = handle

    @classmethod
    def create(cls) -> _Job | None:
        """A new kill-on-close job, or None where jobs are unavailable."""
        if not IS_WINDOWS:
            return None
        try:
            k32 = _kernel32()
            handle = k32.CreateJobObjectW(None, None)
            if not handle:
                return None
            info = _JobLimits()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok = k32.SetInformationJobObject(
                handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                ctypes.sizeof(info),
            )  # fmt: skip
            if not ok:
                k32.CloseHandle(handle)
                return None
            return cls(handle)
        except (OSError, AttributeError, ValueError):
            return None

    def assign(self, pid: int) -> bool:
        """Put the process in the job. False (and the job closed) if Windows refuses."""
        if self._handle is None:
            return False
        try:
            k32 = _kernel32()
            proc = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
            if not proc:
                self.close()
                return False
            try:
                ok = bool(k32.AssignProcessToJobObject(self._handle, proc))
            finally:
                k32.CloseHandle(proc)
        except (OSError, AttributeError, ValueError):
            ok = False
        if not ok:
            # e.g. an enclosing job that forbids nesting (Windows before 8): fall back to
            # taskkill, which needs nothing from us up front.
            self.close()
        return ok

    def terminate(self) -> None:
        """Kill every process still in the job. Never raises."""
        if self._handle is not None:
            with contextlib.suppress(OSError, AttributeError, ValueError):
                _kernel32().TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        """Release the handle; with kill-on-close this also kills any remaining process."""
        handle, self._handle = self._handle, None
        if handle is not None:
            with contextlib.suppress(OSError, AttributeError, ValueError):
                _kernel32().CloseHandle(handle)


_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]  # fmt: skip

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JobLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _k32 = None

    def _kernel32():
        global _k32
        if _k32 is None:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # Explicit signatures: the default int return type would truncate 64-bit handles.
            k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.SetInformationJobObject.argtypes = (
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            )  # fmt: skip
            k32.SetInformationJobObject.restype = wintypes.BOOL
            k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
            k32.AssignProcessToJobObject.restype = wintypes.BOOL
            k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
            k32.TerminateJobObject.restype = wintypes.BOOL
            k32.CloseHandle.argtypes = (wintypes.HANDLE,)
            k32.CloseHandle.restype = wintypes.BOOL
            _k32 = k32
        return _k32


def _reap_leftovers(proc: subprocess.Popen, job: _Job | None) -> None:
    """Kill whatever the finished command left running. Never raises."""
    if IS_WINDOWS:
        if job is not None:
            job.terminate()
        return
    # The session's group id is the leader's pid and stays valid while any member lives.
    with contextlib.suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL)


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
    job: _Job | None = None
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
        job = _Job.create()
        if job is not None and not job.assign(proc.pid):
            job = None

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
            if job is not None:
                job.terminate()  # instant and complete, unlike walking the tree
            else:
                kill_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
        duration = time.monotonic() - start
        _reap_leftovers(proc, job)
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
        if job is not None:
            job.close()
        out.close()
        err.close()
