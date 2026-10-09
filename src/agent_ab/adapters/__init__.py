"""Agent adapters. Each one knows how to launch a particular agent CLI and read its usage."""

from __future__ import annotations

import importlib

from agent_ab.adapters.base import Adapter
from agent_ab.errors import ConfigError

# Imported lazily so a broken or slow adapter module never affects the others.
_REGISTRY: dict[str, str] = {
    "claude-code": "agent_ab.adapters.claude_code:ClaudeCodeAdapter",
    "codex": "agent_ab.adapters.codex:CodexAdapter",
    "command": "agent_ab.adapters.command:CommandAdapter",
    "mock": "agent_ab.adapters.mock:MockAdapter",
}

_INSTANCES: dict[str, Adapter] = {}

ADAPTER_NAMES: tuple[str, ...] = tuple(_REGISTRY)


def get_adapter(name: str) -> Adapter:
    """Return the shared adapter instance registered under ``name``."""
    if name not in _REGISTRY:
        valid = ", ".join(ADAPTER_NAMES)
        raise ConfigError(f"unknown adapter {name!r} (valid: {valid})")
    if name not in _INSTANCES:
        module_name, class_name = _REGISTRY[name].split(":")
        cls = getattr(importlib.import_module(module_name), class_name)
        _INSTANCES[name] = cls()
    return _INSTANCES[name]


__all__ = ["ADAPTER_NAMES", "Adapter", "get_adapter"]
