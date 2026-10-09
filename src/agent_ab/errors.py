"""Exception types shared across agent-ab."""


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


class AdapterError(AgentABError):
    """An agent adapter cannot run (missing executable, bad options)."""


class RunStoreError(AgentABError):
    """A run directory is missing, corrupt, or belongs to a different experiment."""
