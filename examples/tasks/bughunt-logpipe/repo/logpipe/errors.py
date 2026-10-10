"""Exceptions raised by logpipe."""


class LogpipeError(Exception):
    """Base class."""


class ParseError(LogpipeError):
    """A log line could not be parsed."""


class TimestampError(ParseError):
    """A timestamp is not in a supported format."""


class SinkClosed(LogpipeError):
    """A record was added to a sink after it was closed."""
