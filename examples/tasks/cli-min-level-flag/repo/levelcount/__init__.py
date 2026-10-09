"""levelcount: count log lines per severity level."""

from .cli import main
from .parse import LEVELS, count_levels, level_of

__all__ = ["LEVELS", "count_levels", "level_of", "main"]
