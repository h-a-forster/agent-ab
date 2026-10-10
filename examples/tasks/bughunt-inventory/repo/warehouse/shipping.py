"""Shipping cost by parcel weight."""

import math
from decimal import Decimal

from .money import percent_of, round_cents, to_decimal

# (heaviest weight in kg that still belongs to the bracket, price)
BRACKETS = [
    (Decimal("1"), Decimal("5.00")),
    (Decimal("5"), Decimal("9.50")),
    (Decimal("20"), Decimal("18.00")),
]
HEAVY_BASE = Decimal("18.00")
HEAVY_PER_KG = Decimal("1.20")
HEAVY_FROM = Decimal("20")


def shipping_cost(weight_kg):
    """Cost for a parcel.  A parcel of exactly 1 kg costs the first bracket's price (the bracket
    limit itself belongs to the bracket), likewise 5 kg and 20 kg.  Heavier parcels pay the
    20 kg price plus 1.20 for every started kilogram above 20.  Zero weight ships for free."""
    weight = to_decimal(weight_kg)
    if weight <= 0:
        return Decimal("0.00")
    for limit, price in BRACKETS:
        if weight < limit:
            return price
    extra_kg = math.ceil(weight - HEAVY_FROM)
    return round_cents(HEAVY_BASE + HEAVY_PER_KG * extra_kg)


def apply_free_shipping(cost, net_subtotal, threshold):
    """Orders whose net subtotal reaches ``threshold`` (inclusive) ship free; ``None`` disables it."""
    if threshold is not None and to_decimal(net_subtotal) >= to_decimal(threshold):
        return Decimal("0.00")
    return cost


def surcharge(cost, percent):
    """Add a percentage surcharge (for example a fuel surcharge) to a shipping cost."""
    return cost + percent_of(cost, percent)
