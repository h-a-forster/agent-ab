"""Optional ``---`` delimited metadata block at the top of a document."""


def _convert(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_convert(p) for p in inner.split(",")] if inner else []
    try:
        return int(value)
    except ValueError:
        return value


def split_frontmatter(text):
    """Return ``(meta, body)``; ``meta`` is ``{}`` when the document has no metadata block.

    The block starts on the very first line with ``---`` and ends at the next ``---`` line.
    Lines are ``key: value``; the value is everything after the *first* colon.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for end in range(1, len(lines)):
        if lines[end].strip() == "---":
            break
    else:
        return {}, text
    meta = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        meta[key.strip()] = _convert(value)
    return meta, "\n".join(lines[end + 1:])
