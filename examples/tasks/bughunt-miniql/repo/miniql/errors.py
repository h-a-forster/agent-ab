"""Exceptions raised by miniql."""


class SqlError(Exception):
    """Base class for every miniql error."""


class ParseError(SqlError):
    """The query text is not valid SQL for this dialect."""

    def __init__(self, message, pos=None):
        super().__init__(message if pos is None else "%s (at %d)" % (message, pos))
        self.pos = pos


class ExecError(SqlError):
    """The query is valid but cannot be evaluated (bad column, type clash, ...)."""


class CatalogError(SqlError):
    """Unknown table, duplicate table, or a row that does not fit its table."""
