"""Cell references: A1 notation, ranges and relative / absolute shifting."""

import re

from .errors import SheetError

MAX_COL = 16384
MAX_ROW = 1048576
MAX_RANGE_CELLS = 50000

_CELL = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)([0-9]+)$")


def col_to_index(letters):
    """``"A"`` -> 1, ``"Z"`` -> 26, ``"AA"`` -> 27."""
    letters = letters.upper()
    if not letters.isalpha():
        raise SheetError("bad column %r" % letters)
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index


def index_to_col(index):
    """Inverse of ``col_to_index``: 1 -> ``"A"``, 26 -> ``"Z"``, 27 -> ``"AA"``, 702 -> ``"ZZ"``."""
    if index < 1:
        raise SheetError("column index must be >= 1")
    letters = []
    while index > 0:
        index, rem = divmod(index, 26)
        letters.append(chr(ord("A") + rem - 1))
    return "".join(reversed(letters))


class Ref:
    """One cell reference, possibly with ``$`` markers."""

    __slots__ = ("col", "row", "col_abs", "row_abs")

    def __init__(self, col, row, col_abs=False, row_abs=False):
        self.col = col
        self.row = row
        self.col_abs = col_abs
        self.row_abs = row_abs

    @property
    def key(self):
        """Plain cell name without ``$`` markers, e.g. ``"B3"``."""
        return "%s%d" % (index_to_col(self.col), self.row)

    def text(self):
        return "%s%s%s%d" % ("$" if self.col_abs else "", index_to_col(self.col), "$" if self.row_abs else "", self.row)

    def __eq__(self, other):
        return isinstance(other, Ref) and (self.col, self.row, self.col_abs, self.row_abs) == \
            (other.col, other.row, other.col_abs, other.row_abs)

    def __hash__(self):
        return hash((self.col, self.row, self.col_abs, self.row_abs))

    def __repr__(self):
        return "Ref(%s)" % self.text()


def is_ref(text):
    return _CELL.match(text) is not None


def parse_ref(text):
    m = _CELL.match(text.strip())
    if not m:
        raise SheetError("bad cell reference %r" % (text,))
    col = col_to_index(m.group(2))
    row = int(m.group(4))
    if not (1 <= col <= MAX_COL and 1 <= row <= MAX_ROW):
        raise SheetError("cell reference out of range: %r" % (text,))
    return Ref(col, row, bool(m.group(1)), bool(m.group(3)))


def normalize_key(text):
    """``"b3"`` / ``"$B$3"`` -> ``"B3"``."""
    return parse_ref(text).key


def expand_range(start, end):
    """All cell keys of the rectangle spanned by two corner refs, row by row.

    The corners may be given in any order: ``B2:A1`` covers the same cells as ``A1:B2``.
    """
    first = start if isinstance(start, Ref) else parse_ref(start)
    last = end if isinstance(end, Ref) else parse_ref(end)
    c1, c2 = first.col, last.col
    r1, r2 = first.row, last.row
    if (c2 - c1 + 1) * (r2 - r1 + 1) > MAX_RANGE_CELLS:
        raise SheetError("range too large")
    return ["%s%d" % (index_to_col(c), r) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]


def range_shape(start, end):
    first = start if isinstance(start, Ref) else parse_ref(start)
    last = end if isinstance(end, Ref) else parse_ref(end)
    return abs(last.row - first.row) + 1, abs(last.col - first.col) + 1


def shift_ref(ref, drow, dcol):
    """Move a reference like a copied formula: ``$`` parts stay, the rest shifts.

    Returns ``None`` when the shifted reference would fall off the sheet.
    """
    col = ref.col if ref.col_abs else ref.col + dcol
    row = ref.row if ref.col_abs else ref.row + drow
    if not (1 <= col <= MAX_COL and 1 <= row <= MAX_ROW):
        return None
    return Ref(col, row, ref.col_abs, ref.row_abs)


def cell_sort_key(key):
    ref = parse_ref(key)
    return (ref.row, ref.col)
