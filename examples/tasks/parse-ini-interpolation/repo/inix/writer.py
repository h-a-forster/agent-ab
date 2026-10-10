"""Serialise a :class:`~inix.config.Config` back to INI text."""

from __future__ import annotations

from .config import Config


def dumps(config: Config) -> str:
    """Write ``config`` as INI text; continuation lines are indented by four spaces."""
    blocks = []
    for section in config.sections():
        lines = [f"[{section}]"]
        for key in config.keys(section):
            first, *rest = config.get(section, key).split("\n")
            lines.append(f"{key} = {first}".rstrip())
            lines.extend(f"    {line}" for line in rest)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n" if blocks else ""
