"""The adapter contract: how agent-ab launches an agent and reads back what it spent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from agent_ab.model import AgentInvocation, AgentSpec, AgentUsage, ProcResult, TrialContext


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
