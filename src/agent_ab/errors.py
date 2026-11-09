"""Exception types shared across agent-ab."""

from __future__ import annotations

import errno

# The machine ran out of something or its storage failed; no workspace content causes these.
_HOST_ERRNOS = frozenset(
    getattr(errno, name)
    for name in ("ENOSPC", "EDQUOT", "ENOMEM", "EMFILE", "ENFILE", "EAGAIN", "EROFS", "EIO")
    if hasattr(errno, name)
)


def is_host_failure(e: BaseException) -> bool:
    """True when ``e`` says the machine failed (disk full, no memory or handles)."""
    return isinstance(e, MemoryError) or (isinstance(e, OSError) and e.errno in _HOST_ERRNOS)


class AgentABError(Exception):
    """Base class for all agent-ab errors."""


class ConfigError(AgentABError):
    """An experiment or task configuration is invalid.

    ``where`` names the file and key path (e.g. ``experiment.toml: arms[1].agent.model``)
    so the message can point at the exact problem.
    """

    def __init__(self, message: str, where: str | None = None):
        self.where = where
        super().__init__(f"{where}: {message}" if where else message)


class WorkspaceError(AgentABError):
    """Preparing or inspecting a trial workspace failed (counts as an infrastructure error)."""


class GitDirAlteredError(WorkspaceError):
    """A workspace's ``.git`` directory is gone or was replaced, so its diff cannot be taken."""


class HostError(WorkspaceError):
    """The machine failed (disk full, no memory, git cannot start), whatever is in the workspace."""


class AdapterError(AgentABError):
    """An agent adapter cannot run (missing executable, bad options)."""


class RunStoreError(AgentABError):
    """A run directory is missing, corrupt, or belongs to a different experiment."""
