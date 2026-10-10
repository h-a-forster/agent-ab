"""Pipe tables."""

import re

_DELIM_CELL = re.compile(r"^:?-+:?$")


def split_row(line):
    """Split a table row into stripped cells.

    A leading and a trailing ``|`` are optional.  ``\\|`` is a literal pipe inside a cell.
    """
    s = line.strip()
    cells = []
    current = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "|":
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    cells.append("".join(current))
    if s.startswith("|") and cells and cells[0].strip() == "" and not s.startswith("\\|"):
        cells = cells[1:]
    if s.endswith("|") and not s.endswith("\\|") and cells and cells[-1].strip() == "":
        cells = cells[:-1]
    return [c.strip() for c in cells]


def is_delimiter_row(line):
    if "-" not in line:
        return False
    cells = split_row(line)
    return bool(cells) and all(_DELIM_CELL.match(c) for c in cells)


def alignments(line):
    """``['left', 'center', 'right', None]`` style list from a delimiter row."""
    out = []
    for cell in split_row(line):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("center" if left and right else "left" if left else "right" if right else None)
    return out


def normalise(cells, width):
    """Pad with empty cells or cut off extra cells so the row has ``width`` cells."""
    cells = list(cells[:width])
    cells.extend([""] * (width - len(cells)))
    return cells
