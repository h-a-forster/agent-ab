"""Exchange rates and currency conversion."""

from decimal import Decimal, ROUND_HALF_UP

from .errors import LedgerError
from .money import Money


class RateTable:
    """Exchange rates quoted against a base currency.

    ``set_rate("EUR", "USD", "1.10")`` means 1 EUR = 1.10 USD.  The inverse
    rate is derived automatically; rates between two non-base currencies are
    triangulated through the base currency.
    """

    def __init__(self, base="USD"):
        self.base = base
        self._rates = {}

    def set_rate(self, src, dst, rate):
        rate = Decimal(str(rate))
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._rates[(src, dst)] = rate

    def rate(self, src, dst):
        if src == dst:
            return Decimal(1)
        direct = self._lookup(src, dst)
        if direct is not None:
            return direct
        if src != self.base and dst != self.base:
            first = self._lookup(src, self.base)
            second = self._lookup(self.base, dst)
            if first is not None and second is not None:
                return first * second
        raise LedgerError("no rate for %s -> %s" % (src, dst))

    def _lookup(self, src, dst):
        if (src, dst) in self._rates:
            return self._rates[(src, dst)]
        if (dst, src) in self._rates:
            return Decimal(1) / self._rates[(dst, src)]
        return None

    def convert(self, money, dst):
        """Convert ``money`` to ``dst``, rounding half away from zero to a cent."""
        if money.currency == dst:
            return money
        factor = self.rate(money.currency, dst)
        raw = Decimal(money.cents) * factor
        return Money(int(raw.quantize(Decimal(1), rounding=ROUND_HALF_UP)), dst)

    def currencies(self):
        seen = {self.base}
        for src, dst in self._rates:
            seen.add(src)
            seen.add(dst)
        return sorted(seen)
