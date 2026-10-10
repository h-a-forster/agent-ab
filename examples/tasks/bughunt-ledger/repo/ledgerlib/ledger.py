"""The ledger ties a chart, a journal and exchange rates together."""

from .errors import CurrencyMismatch
from .fx import RateTable
from .journal import Journal
from .money import Money


class Ledger:
    def __init__(self, chart, journal=None, rates=None, base="USD"):
        self.chart = chart
        self.journal = journal if journal is not None else Journal()
        self.rates = rates if rates is not None else RateTable(base)
        self.base = base
        self._cache = {}

    # -- writing -----------------------------------------------------------
    def post(self, date, memo, lines, tags=None):
        lines = [l if hasattr(l, "amount") else _line(l) for l in lines]
        for line in lines:
            account = self.chart.get(line.account)
            if line.amount.currency != account.currency:
                raise CurrencyMismatch("%s is a %s account" % (account.code, account.currency))
        entry = self.journal.post(date, memo, lines, tags)
        self._cache.clear()
        return entry

    def reverse(self, entry_id, date=None):
        entry = self.journal.reverse(entry_id, date)
        return entry

    def reverse_many(self, entry_ids, date=None):
        return [self.reverse(i, date) for i in entry_ids]

    # -- reading -----------------------------------------------------------
    def balance(self, code, as_of=None, rollup=False):
        """Debit-positive balance of an account in its own currency.

        With ``rollup=True`` the balances of all descendant accounts are
        included.  ``as_of`` limits the entries considered (inclusive).
        """
        key = (code, as_of, rollup)
        if key in self._cache:
            return self._cache[key]
        codes = [code]
        if rollup:
            codes = [code] + self.chart.descendants(code)
        cents = 0
        for member in codes:
            for entry, amount in self.history(member):
                if as_of is None or entry.date <= as_of:
                    cents += amount.cents
        result = Money(cents, self.chart.get(code).currency)
        self._cache[key] = result
        return result

    def natural_balance(self, code, as_of=None, rollup=False):
        """Balance with the sign flipped for credit-normal accounts."""
        bal = self.balance(code, as_of, rollup)
        return bal if self.chart.get(code).debit_normal else -bal

    def balance_in(self, code, currency, as_of=None, rollup=False):
        return self.rates.convert(self.balance(code, as_of, rollup), currency)

    def history(self, code):
        """(entry, signed Money) pairs touching ``code`` in posting order."""
        rows = []
        for entry in self.journal.entries():
            for line in entry.lines:
                if line.account == code:
                    rows.append((entry, line.amount))
        return rows


def _line(spec):
    from .journal import Line

    return Line(*spec)
