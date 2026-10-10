"""CSV rendering of records."""


def _cell(value):
    text = "" if value is None else str(value)
    if any(ch in text for ch in ',"\n'):
        return '"%s"' % text.replace('"', '""')
    return text


def to_csv(records, columns=None):
    """CSV text with a header row.  Without ``columns`` the header is ``ts,level,msg,host`` followed by
    every field name that occurs, sorted alphabetically."""
    if columns is None:
        extra = sorted({name for r in records for name in r.fields})
        columns = ["ts", "level", "msg", "host"] + extra
    lines = [",".join(_cell(c) for c in columns)]
    for record in records:
        lines.append(",".join(_cell(record.get(c)) for c in columns))
    return "\n".join(lines) + "\n"
