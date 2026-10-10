"""Counters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Stats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
