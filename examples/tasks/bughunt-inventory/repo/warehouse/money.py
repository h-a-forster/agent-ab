"""Decimal money helpers.  Amounts are ``Decimal`` values with two places."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_decimal(value):
    """Decimal from str / int / Decimal (floats are rejected: they carry binary noise)."""
    if isinstance(value, float):
        raise TypeError("use strings or Decimals for money, not floats")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def round_cents(value):
    """Round to whole cents, halves away from zero (``0.005`` -> ``0.01``, ``-0.005`` -> ``-0.01``)."""
    return to_decimal(value).quantize(CENT)


def percent_of(amount, percent):
    """``percent`` percent of ``amount``, rounded to cents."""
    return round_cents(to_decimal(amount) * to_decimal(percent) / 100)


def fmt(amount):
    """``Decimal('1234.5')`` -> ``'1,234.50'``."""
    return "{:,.2f}".format(round_cents(amount))
