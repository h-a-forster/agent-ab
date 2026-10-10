"""inix: a small INI reader and writer."""

from .config import Config, MissingError
from .parser import ParseError, parse
from .writer import dumps

__all__ = ["Config", "MissingError", "ParseError", "dumps", "parse"]
