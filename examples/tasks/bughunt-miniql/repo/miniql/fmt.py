"""Plain-text rendering of query results."""


def render_value(value):
    if value is None:
        return "NULL"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        text = "%.6f" % value
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def format_table(rows, columns=None):
    """Render rows as an aligned text table; numbers are right-aligned."""
    if columns is None:
        columns = list(rows[0]) if rows else []
    if not columns:
        return "(no columns)"
    cells = [[render_value(r.get(c)) for c in columns] for r in rows]
    widths = [len(c) for c in columns]
    for line in cells:
        for i, text in enumerate(line):
            widths[i] = max(widths[i], len(text))
    numeric = [all(isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool)
                   for r in rows if r.get(c) is not None) and bool(rows) for c in columns]

    def fmt_line(parts):
        padded = []
        for i, text in enumerate(parts):
            padded.append(text.rjust(widths[i]) if numeric[i] else text.ljust(widths[i]))
        return " | ".join(padded).rstrip()

    lines = [fmt_line(columns), "-+-".join("-" * w for w in widths)]
    lines.extend(fmt_line(line) for line in cells)
    lines.append("(%d row%s)" % (len(rows), "" if len(rows) == 1 else "s"))
    return "\n".join(lines)
