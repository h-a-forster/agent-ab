"""Immutable money values stored as an integer number of minor units (cents)."""

from .errors import CurrencyMismatch


class Money:
    """An amount of money in one currency, stored as integer cents.

    Money is hashable and immutable.  Arithmetic between different currencies
    raises ``CurrencyMismatch``.
    """

    __slots__ = ("cents", "currency")

    def __init__(self, cents, currency="USD"):
        if isinstance(cents, bool) or not isinstance(cents, int):
            raise TypeError("cents must be an int, got %r" % (cents,))
        object.__setattr__(self, "cents", cents)
        object.__setattr__(self, "currency", currency)

    def __setattr__(self, name, value):
        raise AttributeError("Money is immutable")

    # -- helpers -----------------------------------------------------------
    def _check(self, other):
        if not isinstance(other, Money):
            raise TypeError("expected Money, got %r" % (other,))
        if other.currency != self.currency:
            raise CurrencyMismatch("%s vs %s" % (self.currency, other.currency))

    @classmethod
    def zero(cls, currency="USD"):
        return cls(0, currency)

    # -- arithmetic --------------------------------------------------------
    def __add__(self, other):
        self._check(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other):
        self._check(other)
        return Money(self.cents - other.cents, self.currency)

    def __neg__(self):
        return Money(-self.cents, self.currency)

    def __abs__(self):
        return Money(abs(self.cents), self.currency)

    def __mul__(self, factor):
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise TypeError("Money can only be multiplied by an int")
        return Money(self.cents * factor, self.currency)

    __rmul__ = __mul__

    # -- comparison --------------------------------------------------------
    def __eq__(self, other):
        if not isinstance(other, Money):
            return NotImplemented
        return self.cents == other.cents and self.currency == other.currency

    def __hash__(self):
        return hash((self.cents, self.currency))

    def __lt__(self, other):
        self._check(other)
        return self.cents < other.cents

    def __le__(self, other):
        self._check(other)
        return self.cents <= other.cents

    def __gt__(self, other):
        self._check(other)
        return self.cents > other.cents

    def __ge__(self, other):
        self._check(other)
        return self.cents >= other.cents

    def __bool__(self):
        return self.cents != 0

    def is_zero(self):
        return self.cents == 0

    def is_negative(self):
        return self.cents < 0

    # -- splitting ---------------------------------------------------------
    def allocate(self, ratios):
        """Split into ``len(ratios)`` parts proportional to ``ratios``.

        The parts always sum to the original amount.  Cents left over after
        the proportional (rounded down) shares are handed out one at a time
        to the first parts.  The rule is symmetric for negative amounts:
        ``Money(-100).allocate(r)`` is the mirror image of
        ``Money(100).allocate(r)``.
        """
        ratios = list(ratios)
        if not ratios:
            raise ValueError("need at least one ratio")
        if any(r < 0 for r in ratios) or sum(ratios) == 0:
            raise ValueError("ratios must be non-negative with a positive sum")
        total = sum(ratios)
        sign = -1 if self.cents < 0 else 1
        magnitude = abs(self.cents)
        shares = [magnitude * r // total for r in ratios]
        leftover = magnitude - sum(shares)
        for i in range(leftover):
            shares[i % len(shares)] += 1
        return [Money(sign * s, self.currency) for s in shares]

    def split(self, parts):
        """Split into ``parts`` nearly equal parts (see ``allocate``)."""
        if isinstance(parts, bool) or not isinstance(parts, int) or parts < 1:
            raise ValueError("parts must be a positive int")
        return self.allocate([1] * parts)

    # -- display -----------------------------------------------------------
    def format(self, symbol=None):
        """Render like ``-12.34 USD`` (or ``$12.34`` with a symbol)."""
        sign = "-" if self.cents < 0 else ""
        whole, frac = divmod(abs(self.cents), 100)
        digits = "{:,}".format(whole)
        if symbol:
            return "%s%s%s.%02d" % (sign, symbol, digits, frac)
        return "%s%s.%02d %s" % (sign, digits, frac, self.currency)

    def __str__(self):
        return self.format()

    def __repr__(self):
        return "Money(%d, %r)" % (self.cents, self.currency)


def total(amounts, currency="USD"):
    """Sum an iterable of Money (empty -> zero in ``currency``)."""
    result = Money.zero(currency)
    for amount in amounts:
        result = result + amount
    return result
