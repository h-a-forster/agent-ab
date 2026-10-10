"""miniargs: declarative argument parsing without sys.exit."""

from .parser import Parser, UsageError
from .result import Namespace
from .spec import Option, Positional

__all__ = ["Namespace", "Option", "Parser", "Positional", "UsageError"]
