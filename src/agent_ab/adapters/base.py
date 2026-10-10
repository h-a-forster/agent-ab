"""The adapter contract: how agent-ab launches an agent and reads back what it spent."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from agent_ab.errors import AdapterError
from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext
from agent_ab.proc import build_env

IS_WINDOWS = os.name == "nt"

_BATCH_SUFFIXES = frozenset({".cmd", ".bat"})
# cmd.exe re-parses the command line of a batch file: these characters can start a new
# command, redirect output, expand variables, or end the argument list early.
_BATCH_UNSAFE = re.compile(r'[&|<>^%!"\r\n]')


class Adapter(ABC):
    """Translates an ``AgentSpec`` into a process invocation and parses its output.

    Adapters are stateless; one instance serves every trial, possibly from several threads.
    """

    #: Name used in configuration files (``adapter = "..."``).
    name: str = ""

    #: Option keys this adapter accepts under ``[agent.options]``. Unknown keys are a config error.
    option_keys: frozenset[str] = frozenset()

    def validate(self, spec: AgentSpec) -> list[str]:
        """Return configuration problems for ``spec`` (empty list = valid). No side effects."""
        unknown = sorted(set(spec.options) - self.option_keys)
        return [f"unknown option {k!r} for adapter {self.name!r}" for k in unknown]

    def check_available(self, spec: AgentSpec) -> str | None:
        """Return a message if the agent cannot be launched on this machine, else None."""
        return None

    def version(self, spec: AgentSpec) -> str | None:
        """The agent CLI's version, or None when unknown. Must never raise; called once per arm."""
        return None

    @abstractmethod
    def build(self, ctx: TrialContext) -> AgentInvocation:
        """Build the process invocation for one attempt. May write files under ``ctx.artifacts``."""

    @abstractmethod
    def parse(self, ctx: TrialContext, result: ProcResult) -> AgentUsage:
        """Extract usage from the finished process. Must never raise on malformed output."""


def read_text(path: Path, limit: int | None = None) -> str:
    """Read a captured output file leniently (missing file -> empty string, bad bytes replaced)."""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if limit is not None and len(data) > limit:
        data = data[-limit:]
    return data.decode("utf-8", errors="replace")


def read_head(path: Path, limit: int) -> str:
    """The first ``limit`` bytes of a captured output file (``read_text`` keeps the tail)."""
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


_VERSION_NUMBER = re.compile(r"\d+(?:\.\d+)+\S*")
_VERSION_TIMEOUT_S = 15.0


def probe_version(spec: AgentSpec, default_exe: str) -> str | None:
    """Run ``<executable> --version`` and return the version number it prints, else None.

    Falls back to the first output line when no dotted number is found. Never raises: a
    missing executable, a timeout or a non-zero exit all mean "unknown".
    """
    exe = spec.options.get("executable", default_exe)
    if not isinstance(exe, str) or not exe.strip():
        return None
    try:
        proc = subprocess.run(
            [shutil.which(exe) or exe, "--version"],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=build_env(spec.env),
            timeout=_VERSION_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    lines = proc.stdout.decode("utf-8", errors="replace").strip().splitlines()
    if not lines or not lines[0].strip():
        return None
    match = _VERSION_NUMBER.search(lines[0])
    return (match.group(0) if match else lines[0].strip())[:100]


def is_batch_file(path: str | None) -> bool:
    """Whether ``path`` names a Windows batch file (``.cmd``/``.bat``), e.g. an npm shim."""
    return bool(path) and Path(path).suffix.lower() in _BATCH_SUFFIXES


def batch_argv_problems(argv: Sequence[str]) -> list[str]:
    """Describe the arguments that cmd.exe would re-parse if ``argv[0]`` is a batch file.

    Pure: looks only at the ``argv[0]`` suffix, so it behaves the same on every platform.
    Returns an empty list when ``argv[0]`` is not a batch file or every argument is safe.
    """
    if not argv or not is_batch_file(argv[0]):
        return []
    problems = []
    for arg in argv[1:]:
        bad = sorted(set(_BATCH_UNSAFE.findall(arg)))
        if bad:
            shown = ", ".join(repr(c) for c in bad)
            problems.append(f"argument {arg[:80]!r} contains {shown}")
    if not problems:
        return []
    return [
        f"{Path(argv[0]).name} is a Windows batch file, and cmd.exe re-parses its arguments "
        "(it can run injected commands, expand %variables% or cut text at a newline): "
        + "; ".join(problems)
        + ". Install the native executable and point [agent.options].executable at it, "
        "or avoid these characters"
    ]


def batch_argv_issue(argv: Sequence[str]) -> str | None:
    """``batch_argv_problems`` for this platform: always None off Windows, where a ``.cmd``
    suffix has no special meaning."""
    if not IS_WINDOWS:
        return None
    problems = batch_argv_problems(argv)
    return problems[0] if problems else None


def check_batch_argv(argv: Sequence[str]) -> None:
    """Raise ``AdapterError`` if ``argv`` cannot be passed safely through a Windows batch file."""
    issue = batch_argv_issue(argv)
    if issue:
        raise AdapterError(issue)
