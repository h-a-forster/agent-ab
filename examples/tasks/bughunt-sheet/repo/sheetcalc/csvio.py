"""Reading and writing sheets as CSV."""

from .format import format_value
from .refs import index_to_col, parse_ref
from .sheet import Sheet


def split_line(line):
    cells, current, quoted, i = [], [], False, 0
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == '"' and line[i + 1:i + 2] == '"':
                current.append('"')
                i += 1
            elif ch == '"':
                quoted = False
            else:
                current.append(ch)
        elif ch == '"':
            quoted = True
        elif ch == ",":
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    cells.append("".join(current))
    return cells


def load_csv(text, origin="A1"):
    """A new Sheet whose top-left cell is ``origin``; each cell's text is its raw content."""
    start = parse_ref(origin)
    sheet = Sheet()
    for r, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        for c, raw in enumerate(split_line(line)):
            if raw != "":
                sheet.set("%s%d" % (index_to_col(start.col + c), start.row + r), raw)
    return sheet


def _quote(text):
    if any(ch in text for ch in ',"\n'):
        return '"%s"' % text.replace('"', '""')
    return text


def dump_csv(sheet, formulas=False):
    """CSV of the used rectangle (from A1); values by default, raw text with ``formulas=True``."""
    keys = sheet.cells()
    if not keys:
        return ""
    refs = [parse_ref(k) for k in keys]
    max_row = max(r.row for r in refs)
    max_col = max(r.col for r in refs)
    lines = []
    for row in range(1, max_row + 1):
        cells = []
        for col in range(1, max_col + 1):
            key = "%s%d" % (index_to_col(col), row)
            cells.append(_quote(sheet.raw(key) if formulas else format_value(sheet.get(key))))
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"
