"""Line-oriented INI parser. Produces ``{section: {key: raw_value}}`` in file order."""

from __future__ import annotations


class ParseError(ValueError):
    def __init__(self, message: str, line: int) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


def parse(text: str) -> dict[str, dict[str, str]]:
    """Parse INI text.

    * blank lines and lines starting with ``#`` or ``;`` (after optional indentation) are skipped
    * ``[name]`` starts a section (reopening a section merges into it)
    * ``key = value`` splits at the first ``=``; key and value are stripped; a repeated key
      keeps the last value
    * an indented non-blank line continues the previous value, joined with ``"\\n"``
    """
    data: dict[str, dict[str, str]] = {}
    section: dict[str, str] | None = None
    last_key: str | None = None
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue
        if line[0] in " \t" and section is not None and last_key is not None:
            section[last_key] += "\n" + stripped
            continue
        if stripped.startswith("["):
            if not stripped.endswith("]") or not stripped[1:-1].strip():
                raise ParseError("malformed section header", lineno)
            name = stripped[1:-1].strip()
            section = data.setdefault(name, {})
            last_key = None
            continue
        if section is None:
            raise ParseError("key outside of any section", lineno)
        if "=" not in stripped:
            raise ParseError("expected 'key = value'", lineno)
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key:
            raise ParseError("empty key", lineno)
        section[key] = value.strip()
        last_key = key
    return data
