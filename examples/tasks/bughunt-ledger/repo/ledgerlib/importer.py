"""Importing entries from simple CSV-like text."""

from datetime import date

from .errors import ImportFailure
from .money import Money


def parse_amount(text):
    """Parse ``"1,234.50"``, ``"$5"``, ``"-0.05"`` or ``"(12.50)"`` into integer cents.

    Parentheses mean negative.  At most two decimal places are allowed.
    """
    s = text.strip()
    if not s:
        raise ImportFailure("empty amount")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()
    s = s.replace("$", "").replace(",", "")
    whole, _, frac = s.partition(".")
    digits = whole.lstrip("-")
    if not (digits or frac) or not (digits + frac).isdigit() or len(frac) > 2:
        raise ImportFailure("bad amount %r" % text)
    units = int(whole) if digits else 0
    cents = units * 100 + int(frac.ljust(2, "0") or "0") * (-1 if units < 0 else 1)
    return -cents if negative else cents


def _leap(year):
    return year % 4 == 0 and year % 100 != 0


def _valid_date(year, month, day):
    limits = [31, 29 if _leap(year) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return 1 <= month <= 12 and 1 <= day <= limits[month - 1]


def parse_date(text):
    """Parse ``YYYY-MM-DD`` or ``MM/DD/YYYY`` into a date."""
    s = text.strip()
    try:
        if "-" in s:
            y, m, d = (int(p) for p in s.split("-"))
        else:
            m, d, y = (int(p) for p in s.split("/"))
    except ValueError:
        raise ImportFailure("bad date %r" % text) from None
    if not _valid_date(y, m, d):
        raise ImportFailure("bad date %r" % text)
    return date(y, m, d)


def split_row(line):
    """Split one CSV row on commas, honouring double quotes."""
    cells, current, quoted = [], [], False
    for ch in line:
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    cells.append("".join(current).strip())
    return cells


def import_csv(text, ledger, cash_account, currency="USD"):
    """Post one entry per row of ``date,memo,amount,counter_account``.

    A positive amount moves money into ``cash_account`` (debit) from the
    counter account; a negative amount moves it out.  A header row starting
    with ``date`` is skipped.  Returns the list of posted entries.
    """
    posted = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        cells = split_row(raw)
        if number == 1 and cells[0].lower() == "date":
            continue
        if len(cells) != 4:
            raise ImportFailure("expected 4 columns, got %d" % len(cells), number)
        try:
            when = parse_date(cells[0])
            cents = parse_amount(cells[2])
        except ImportFailure as exc:
            raise ImportFailure(str(exc), number) from None
        amount = Money(cents, currency)
        posted.append(ledger.post(when, cells[1], [(cash_account, amount), (cells[3], -amount)]))
    return posted
