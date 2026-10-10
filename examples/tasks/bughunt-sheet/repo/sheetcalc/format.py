"""Turning values into display text."""

from .errors import CellError


def format_value(value):
    if value is None:
        return ""
    if isinstance(value, CellError):
        return value.code
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return "#NUM!"
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return "%.10g" % value
    return str(value)


def render_grid(sheet, top_left, bottom_right):
    """A text table of the cells in the rectangle, with column letters and row numbers."""
    from .refs import index_to_col, parse_ref

    a, b = parse_ref(top_left), parse_ref(bottom_right)
    cols = list(range(min(a.col, b.col), max(a.col, b.col) + 1))
    rows = list(range(min(a.row, b.row), max(a.row, b.row) + 1))
    table = [[""] + [index_to_col(c) for c in cols]]
    for r in rows:
        line = [str(r)]
        for c in cols:
            line.append(format_value(sheet.get("%s%d" % (index_to_col(c), r))))
        table.append(line)
    widths = [max(len(row[i]) for row in table) for i in range(len(cols) + 1)]
    out = []
    for row in table:
        cells = []
        for i, text in enumerate(row):
            numeric = i > 0 and text[:1].lstrip("-").isdigit()
            cells.append(text.rjust(widths[i]) if numeric or i == 0 else text.ljust(widths[i]))
        out.append(" ".join(cells).rstrip())
    return "\n".join(out)
