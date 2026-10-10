"""Line handling. A "line" is a str that keeps its own line ending; only "\\n" ends a line."""
import re

_LINE = re.compile(r"[^\n]*\n|[^\n]+")


def split_lines(text):
    """'a\\nb' -> ['a\\n', 'b']; '' -> []. Other control characters (\\r, \\x0c, ...) do not split."""
    return _LINE.findall(text)


def join_lines(lines):
    return "".join(lines)
