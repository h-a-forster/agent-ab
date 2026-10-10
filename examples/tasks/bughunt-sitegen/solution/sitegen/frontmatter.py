"""Front matter: a ``---`` delimited block of ``key: value`` lines at the top of a file."""

import datetime

from .errors import FrontMatterError


def parse_scalar(text):
    """Quoted string, bool, int, ISO date, ``[a, b]`` list or plain string."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [parse_scalar(part) for part in inner.split(",")] if inner else []
    lowered = text.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if lowered in ("null", "~", ""):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return text


def split(text):
    """Return ``(meta dict, body)``.  Files without front matter give ``({}, text)``."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        raise FrontMatterError("front matter is not closed")
    block = text[4:end]
    rest = text[end + 4:]
    if rest.startswith("\n"):
        rest = rest[1:]
    meta = {}
    for number, line in enumerate(block.split("\n"), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise FrontMatterError("line %d: expected 'key: value'" % number)
        meta[key.strip()] = parse_scalar(value)
    return meta, rest
