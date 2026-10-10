"""The Transition record."""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Transition:
    source: str
    event: str
    target: Optional[str] = None  # None: internal transition
    guard: Optional[Callable[[dict], bool]] = None
    action: Optional[Callable[[dict], None]] = None
