"""inix: a small INI reader and writer."""

from .config import Config, MissingError
from .interpolate import InterpolationError
from .parser import ParseError, parse
from .writer import dumps

__all__ = ["Config", "InterpolationError", "MissingError", "ParseError", "dumps", "parse"]
