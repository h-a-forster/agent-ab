from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from agent_ab.proc import IS_WINDOWS, build_env, kill_tree, resolve_executable, run_process

PY = sys.executable


def _run(tmp_path: Path, argv, **kw):
    kw.setdefault("cwd", tmp_path)
    kw.setdefault("env", None)
    kw.setdefault("timeout_s", 30)
    return run_process(
        argv, stdout_path=tmp_path / "out.txt", stderr_path=tmp_path / "err.txt", **kw
    )


def _alive(pid: int) -> bool:
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # an unreaped zombie is dead for our purposes
        with open(f"/proc/{pid}/status") as fh:
            return not any(line.startswith("State:\tZ") for line in fh)
    except OSError:
        return True


def _wait_dead(pid: int, within_s: float) -> bool:
    deadline = time.monotonic() + within_s
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def test_success_captures_output_and_exit_code(tmp_path):
    code = "import sys; print('hello'); print('oops', file=sys.stderr); sys.exit(3)"
    r = _run(tmp_path, [PY, "-c", code])
    assert r.exit_code == 3
    assert not r.timed_out
    assert r.start_error is None
    assert r.duration_s >= 0
    assert (tmp_path / "out.txt").read_text().strip() == "hello"
    assert (tmp_path / "err.txt").read_text().strip() == "oops"


def test_output_dirs_are_created(tmp_path):
    r = run_process(
        [PY, "-c", "print(1)"],
        cwd=tmp_path,
        env=None,
        timeout_s=30,
        stdout_path=tmp_path / "a" / "b" / "out",
        stderr_path=tmp_path / "a" / "c" / "err",
    )
    assert r.exit_code == 0
    assert (tmp_path / "a" / "b" / "out").read_text().strip() == "1"


def test_cwd_is_respected(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    r = _run(tmp_path, [PY, "-c", "import os; print(os.getcwd())"], cwd=sub)
    assert r.exit_code == 0
    assert Path((tmp_path / "out.txt").read_text().strip()).resolve() == sub.resolve()


def test_timeout_kills_and_reports(tmp_path):
    t0 = time.monotonic()
    r = _run(tmp_path, [PY, "-c", "import time; time.sleep(60)"], timeout_s=0.5)
    assert r.timed_out
    assert r.exit_code is None
    assert r.start_error is None
    assert time.monotonic() - t0 < 15


def test_timeout_kills_whole_tree(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    child = textwrap.dedent(
        f"""
        import subprocess, sys, time
        gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        with open({str(pidfile)!r}, "w") as fh:
            fh.write(str(gc.pid))
        time.sleep(60)
        """
    )
    t0 = time.monotonic()
    r = _run(tmp_path, [PY, "-c", child], timeout_s=1.0)
    elapsed = time.monotonic() - t0
    assert r.timed_out
    assert elapsed < 10, elapsed
    assert pidfile.exists(), "child did not start the grandchild before the timeout"
    gc_pid = int(pidfile.read_text())
    assert _wait_dead(gc_pid, 5), f"grandchild {gc_pid} survived the tree kill"


def test_cancel_kills_tree(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    child = textwrap.dedent(
        f"""
        import subprocess, sys, time
        gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        with open({str(pidfile)!r}, "w") as fh:
            fh.write(str(gc.pid))
        time.sleep(60)
        """
    )
    cancel = threading.Event()

    def trigger():
        deadline = time.monotonic() + 10
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        cancel.set()

    threading.Thread(target=trigger, daemon=True).start()
    t0 = time.monotonic()
    r = _run(tmp_path, [PY, "-c", child], timeout_s=60, cancel=cancel)
    assert time.monotonic() - t0 < 20
    assert r.exit_code is None
    assert r.timed_out is False
    assert r.start_error is None
    assert _wait_dead(int(pidfile.read_text()), 5)


def test_precancelled_event_returns_quickly(tmp_path):
    cancel = threading.Event()
    cancel.set()
    t0 = time.monotonic()
    r = _run(tmp_path, [PY, "-c", "import time; time.sleep(60)"], cancel=cancel)
    assert r.exit_code is None and not r.timed_out
    assert time.monotonic() - t0 < 10


def test_large_stdin_does_not_deadlock(tmp_path):
    prompt = ("x" * 1023 + "\n") * 2048 + "end é"  # > 2 MB, with non-ASCII
    code = (
        "import sys; data = sys.stdin.buffer.read(); "
        "sys.stdout.write(str(len(data))); sys.stderr.buffer.write(data[-6:])"
    )
    r = _run(tmp_path, [PY, "-c", code], stdin_text=prompt, timeout_s=60)
    assert r.exit_code == 0
    assert int((tmp_path / "out.txt").read_text()) == len(prompt.encode("utf-8"))
    assert (tmp_path / "err.txt").read_bytes().decode("utf-8") == "end é"


def test_large_stdin_ignored_by_child(tmp_path):
    # The child exits without reading; the writer must swallow the broken pipe.
    r = _run(tmp_path, [PY, "-c", "print('bye')"], stdin_text="y" * (3 * 1024 * 1024))
    assert r.exit_code == 0
    assert r.start_error is None


def test_no_stdin_means_eof(tmp_path):
    r = _run(tmp_path, [PY, "-c", "import sys; print(repr(sys.stdin.read()))"])
    assert r.exit_code == 0
    assert (tmp_path / "out.txt").read_text().strip() == "''"


def test_missing_executable_is_start_error(tmp_path):
    r = _run(tmp_path, ["definitely-not-a-real-program-xyz", "--help"])
    assert r.exit_code is None
    assert r.start_error and "not found" in r.start_error
    assert not r.timed_out
    assert (tmp_path / "out.txt").exists()


def test_missing_executable_path_is_start_error(tmp_path):
    r = _run(tmp_path, [str(tmp_path / "nope" / "prog")])
    assert r.exit_code is None
    assert r.start_error


def test_bad_cwd_is_start_error(tmp_path):
    r = _run(tmp_path, [PY, "-c", "pass"], cwd=tmp_path / "missing")
    assert r.exit_code is None
    assert r.start_error and "working directory" in r.start_error


def test_empty_argv_is_start_error(tmp_path):
    r = _run(tmp_path, [])
    assert r.exit_code is None and r.start_error


@pytest.mark.skipif(IS_WINDOWS, reason="POSIX execute permission")
def test_permission_denied_is_start_error(tmp_path):
    prog = tmp_path / "prog.sh"
    prog.write_text("#!/bin/sh\necho hi\n")
    prog.chmod(0o644)
    r = _run(tmp_path, [str(prog)])
    assert r.exit_code is None
    assert r.start_error


def test_shell_string(tmp_path):
    r = _run(tmp_path, f'"{PY}" -c "print(6*7)"')
    assert r.exit_code == 0
    assert (tmp_path / "out.txt").read_text().strip() == "42"


def test_shell_string_exit_code(tmp_path):
    r = _run(tmp_path, "exit 5")
    assert r.exit_code == 5


def test_shell_flag_with_argv(tmp_path):
    r = _run(tmp_path, [PY, "-c", "print('a b')"], shell=True)
    assert r.exit_code == 0
    assert (tmp_path / "out.txt").read_text().strip() == "a b"


def test_env_is_passed(tmp_path):
    env = build_env({"AGENT_AB_TEST_VAR": "v1"})
    r = _run(tmp_path, [PY, "-c", "import os; print(os.environ['AGENT_AB_TEST_VAR'])"], env=env)
    assert r.exit_code == 0
    assert (tmp_path / "out.txt").read_text().strip() == "v1"


def test_build_env_merges_over_os_environ(monkeypatch):
    monkeypatch.setenv("AGENT_AB_BASE", "base")
    env = build_env({"AGENT_AB_NEW": 5, "AGENT_AB_BASE": "over"})  # type: ignore[dict-item]
    assert env["AGENT_AB_NEW"] == "5"
    assert env["AGENT_AB_BASE"] == "over"
    assert "AGENT_AB_NEW" not in os.environ
    assert build_env(None) == dict(os.environ)


@pytest.mark.skipif(not IS_WINDOWS, reason="case-insensitive environment")
def test_build_env_windows_case_insensitive():
    env = build_env({"Path": "X"})
    assert [k for k in env if k.upper() == "PATH"] == ["Path"]
    assert env["Path"] == "X"


def test_resolve_executable_python():
    found = resolve_executable(PY)
    assert found and Path(found).samefile(PY)
    assert resolve_executable("definitely-not-a-real-program-xyz") is None
    assert resolve_executable("") is None


def test_resolve_executable_cmd_shim(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if IS_WINDOWS:
        shim = bindir / "fakeagent.cmd"
        shim.write_text(f'@"{PY}" -c "print(\'shim ok\')" %*\r\n')
        # npm also installs an extension-less shell script that Windows cannot launch.
        (bindir / "fakeagent").write_text("#!/bin/sh\necho no\n")
    else:
        shim = bindir / "fakeagent"
        shim.write_text(f"#!/bin/sh\nexec '{PY}' -c \"print('shim ok')\" \"$@\"\n")
        shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    found = resolve_executable("fakeagent")
    assert found and Path(found).samefile(shim)
    r = _run(tmp_path, ["fakeagent", "--x"])
    assert r.exit_code == 0, (tmp_path / "err.txt").read_text()
    assert (tmp_path / "out.txt").read_text().strip() == "shim ok"


def test_kill_tree_on_finished_process_is_safe(tmp_path):
    p = subprocess.Popen([PY, "-c", "pass"])
    p.wait()
    kill_tree(p)  # must not raise


def test_kill_tree_direct(tmp_path):
    kw = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if IS_WINDOWS
        else {"start_new_session": True}
    )
    p = subprocess.Popen([PY, "-c", "import time; time.sleep(60)"], **kw)
    kill_tree(p)
    p.wait(timeout=10)
    assert p.returncode is not None
