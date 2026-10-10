"""Log levels."""

from .errors import ParseError

ORDER = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")

ALIASES = {
    "TRACE": "DEBUG", "DBG": "DEBUG", "INFORMATION": "INFO", "NOTICE": "INFO",
    "WARNING": "WARN", "ERR": "ERROR", "SEVERE": "ERROR", "CRIT": "FATAL", "CRITICAL": "FATAL", "EMERG": "FATAL",
}


def parse_level(text, default=None):
    """Canonical level name (``"warning"`` -> ``"WARN"``).  Unknown text gives ``default`` or an error."""
    if text is None or str(text).strip() == "":
        if default is not None:
            return default
        raise ParseError("missing level")
    name = str(text).strip().upper()
    name = ALIASES.get(name, name)
    if name in ORDER:
        return name
    if default is not None:
        return default
    raise ParseError("unknown level %r" % (text,))


def rank(level):
    """Position of a level in severity order (DEBUG = 0 ... FATAL = 4)."""
    return ORDER.index(parse_level(level))


def at_least(level, minimum):
    return rank(level) >= rank(minimum)


def from_status(status):
    """Level for an HTTP status code: 5xx -> ERROR, 4xx -> WARN, everything else INFO."""
    if status >= 500:
        return "ERROR"
    if status >= 400:
        return "WARN"
    return "INFO"
