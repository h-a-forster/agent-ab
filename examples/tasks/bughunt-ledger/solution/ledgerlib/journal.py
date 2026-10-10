"""The journal: an append-only list of balanced entries."""

from .errors import LedgerError, UnbalancedEntry
from .money import Money


class Line:
    """One side of an entry.  Positive amounts are debits, negative are credits."""

    __slots__ = ("account", "amount")

    def __init__(self, account, amount):
        if not isinstance(amount, Money):
            raise TypeError("amount must be Money")
        self.account = account
        self.amount = amount

    def __repr__(self):
        return "Line(%r, %r)" % (self.account, self.amount)

    def __eq__(self, other):
        return isinstance(other, Line) and (self.account, self.amount) == (other.account, other.amount)

    def __hash__(self):
        return hash((self.account, self.amount))


class Entry:
    def __init__(self, id, date, memo, lines, tags=None, reverses=None):
        self.id = id
        self.date = date
        self.memo = memo
        self.lines = list(lines)
        self.tags = list(tags) if tags else []
        self.reverses = reverses
        self.reversed_by = None

    def add_tag(self, tag):
        if tag not in self.tags:
            self.tags.append(tag)

    def has_tag(self, tag):
        return tag in self.tags

    def accounts(self):
        return sorted({line.account for line in self.lines})

    def __repr__(self):
        return "Entry(#%d %s %r)" % (self.id, self.date.isoformat(), self.memo)


def check_balanced(lines):
    if len(lines) < 2:
        raise UnbalancedEntry("an entry needs at least two lines")
    sums = {}
    for line in lines:
        cur = line.amount.currency
        sums[cur] = sums.get(cur, 0) + line.amount.cents
    bad = {cur: cents for cur, cents in sums.items() if cents != 0}
    if bad:
        raise UnbalancedEntry("unbalanced in %s" % ", ".join("%s %+d" % kv for kv in sorted(bad.items())))


class Journal:
    def __init__(self):
        self._entries = []
        self._next_id = 1

    def post(self, date, memo, lines, tags=None, reverses=None):
        lines = [l if isinstance(l, Line) else Line(*l) for l in lines]
        check_balanced(lines)
        entry = Entry(self._next_id, date, memo, lines, tags, reverses)
        self._next_id += 1
        self._entries.append(entry)
        return entry

    def get(self, entry_id):
        for entry in self._entries:
            if entry.id == entry_id:
                return entry
        raise LedgerError("no entry #%s" % (entry_id,))

    def entries(self):
        return list(self._entries)

    def __len__(self):
        return len(self._entries)

    def between(self, start, end):
        """Entries dated from ``start`` to ``end``, both inclusive, in posting order."""
        return [e for e in self._entries if start <= e.date <= end]

    def up_to(self, as_of):
        return [e for e in self._entries if as_of is None or e.date <= as_of]

    def for_account(self, code):
        return [e for e in self._entries if any(l.account == code for l in e.lines)]

    def tagged(self, tag):
        return [e for e in self._entries if e.has_tag(tag)]

    def reverse(self, entry_id, date=None):
        """Post the mirror image of an entry and link the two."""
        original = self.get(entry_id)
        if original.reversed_by is not None:
            raise LedgerError("entry #%d is already reversed" % entry_id)
        if original.reverses is not None:
            raise LedgerError("entry #%d is itself a reversal" % entry_id)
        lines = [Line(l.account, -l.amount) for l in original.lines]
        memo = "Reversal of #%d: %s" % (original.id, original.memo)
        entry = self.post(date or original.date, memo, lines, tags=original.tags, reverses=original.id)
        original.reversed_by = entry.id
        return entry
