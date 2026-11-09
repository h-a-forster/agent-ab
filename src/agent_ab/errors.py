"""Exception types shared across agent-ab."""

from __future__ import annotations

import errno

# The machine ran out of something or its storage failed; no workspace content causes these.
_HOST_ERRNOS = frozenset(
    getattr(errno, name)
    for name in ("ENOSPC", "EDQUOT", "ENOMEM", "EMFILE", "ENFILE", "EAGAIN", "EROFS", "EIO")
    if hasattr(errno, name)
)
# Python maps many Windows errors to EINVAL, so these need their own check: not enough memory,
# outofmemory, handle disk full, disk full, no system resources, nonpaged and paged pool, working
# set quota, paging file quota, commitment limit.
_HOST_WINERRORS = frozenset({8, 14, 39, 112, 1450, 1451, 1452, 1453, 1454, 1455})


def is_host_failure(e: BaseException) -> bool:
    """True when ``e`` says the machine failed (disk full, no memory or handles)."""
    if isinstance(e, MemoryError):
        return True
    if not isinstance(e, OSError):
        return False
    return e.errno in _HOST_ERRNOS or getattr(e, "winerror", None) in _HOST_WINERRORS


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
    """The machine failed (disk full, no memory, a stalled git), whatever is in the workspace."""


class AdapterError(AgentABError):
    """An agent adapter cannot run (missing executable, bad options)."""


class RunStoreError(AgentABError):
    """A run directory is missing, corrupt, or belongs to a different experiment."""
