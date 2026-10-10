"""miniql: a tiny SQL-like query engine over lists of dicts."""

from .catalog import Database, Table
from .errors import CatalogError, ExecError, ParseError, SqlError
from .executor import execute, run_sql
from .fmt import format_table
from .parser import parse

__all__ = ["Database", "Table", "SqlError", "ParseError", "ExecError", "CatalogError",
           "parse", "execute", "run_sql", "format_table"]
