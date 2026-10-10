"""Declarations of options and positionals."""

from dataclasses import dataclass
from typing import Any, Callable

KINDS = ("flag", "value")


@dataclass(frozen=True)
class Option:
    name: str
    short: str | None = None
    kind: str = "value"
    type: Callable[[str], Any] = str
    default: Any = None
    required: bool = False

    def __post_init__(self):
        if not self.name or self.name.startswith("-"):
            raise ValueError(f"bad option name {self.name!r}")
        if self.kind not in KINDS:
            raise ValueError(f"unknown kind {self.kind!r}")
        if self.short is not None and (len(self.short) != 1 or not self.short.isalpha()):
            raise ValueError(f"short name must be one letter: {self.short!r}")

    @property
    def key(self):
        return self.name.replace("-", "_")

    @property
    def flag(self):
        return "--" + self.name


@dataclass(frozen=True)
class Positional:
    name: str
    type: Callable[[str], Any] = str
    required: bool = True
    many: bool = False  # collect all remaining positionals into a list

    @property
    def key(self):
        return self.name.replace("-", "_")
