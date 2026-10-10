"""Stock reports."""

from decimal import Decimal

from .money import round_cents


class ReorderRow:
    def __init__(self, sku, on_hand, minimum):
        self.sku = sku
        self.on_hand = on_hand
        self.minimum = minimum
        self.shortfall = minimum - on_hand

    def __repr__(self):
        return "ReorderRow(%s short %d)" % (self.sku, self.shortfall)


def reorder_report(stock, minimums, now=None):
    """SKUs whose usable stock is below their minimum, biggest shortfall first; equal shortfalls
    are listed in SKU order (A to Z)."""
    rows = []
    for sku, minimum in minimums.items():
        on_hand = stock.on_hand(sku, now)
        if on_hand < minimum:
            rows.append(ReorderRow(sku, on_hand, minimum))
    rows.sort(key=lambda r: (-r.shortfall, r.sku))
    return rows


def expiring_soon(stock, now, within):
    """Lots (with stock) that expire from ``now`` up to ``now + within`` days, inclusive, soonest
    first (ties by lot id)."""
    lots = []
    for lot_id in stock.snapshot():
        lot = stock.lot(lot_id)
        if lot.qty > 0 and lot.expires is not None and now <= lot.expires <= now + within:
            lots.append(lot)
    return sorted(lots, key=lambda l: (l.expires, l.id))


def valuation(stock, catalog, now=None):
    """Value of usable stock at list price, per SKU and in total."""
    per_sku = {}
    for sku in catalog.skus():
        qty = stock.on_hand(sku, now)
        if qty:
            per_sku[sku] = round_cents(catalog.get(sku).unit_price * qty)
    total = round_cents(sum(per_sku.values(), Decimal("0.00")))
    return per_sku, total


def stock_levels(stock, catalog, now):
    """``[(sku, on_hand, reserved, available)]`` for every SKU in the catalog, sorted by SKU."""
    rows = []
    for sku in catalog.skus():
        rows.append((sku, stock.on_hand(sku, now), stock.book.reserved_qty(sku, now), stock.available(sku, now)))
    return rows
