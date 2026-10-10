"""Lots of stock, first-expired-first-out allocation and availability."""

from .errors import InsufficientStock, WarehouseError
from .reservations import ReservationBook


class Lot:
    def __init__(self, lot_id, sku, qty, received, expires=None):
        if qty < 0:
            raise WarehouseError("lot quantity must not be negative")
        self.id = lot_id
        self.sku = sku
        self.qty = qty
        self.received = received
        self.expires = expires

    def __repr__(self):
        return "Lot(%s %s x%d)" % (self.id, self.sku, self.qty)


def fefo_key(lot):
    """Allocation order: earliest expiry first; lots that never expire come after every lot
    that does; ties by the earlier receipt date, then by lot id."""
    return (lot.expires or 0, lot.received, lot.id)


class Stock:
    def __init__(self, book=None):
        self._lots = {}
        self.book = book if book is not None else ReservationBook()

    # -- lots ------------------------------------------------------------
    def add_lot(self, lot_id, sku, qty, received, expires=None):
        if lot_id in self._lots:
            raise WarehouseError("duplicate lot %s" % lot_id)
        lot = Lot(lot_id, sku, qty, received, expires)
        self._lots[lot_id] = lot
        return lot

    def lot(self, lot_id):
        try:
            return self._lots[lot_id]
        except KeyError:
            raise WarehouseError("unknown lot %s" % lot_id) from None

    def lots_for(self, sku, now=None):
        """Lots of ``sku`` with stock, in allocation (FEFO) order.  Lots already expired at
        ``now`` (``expires <= now``) are left out when ``now`` is given."""
        lots = [l for l in self._lots.values() if l.sku == sku and l.qty > 0]
        if now is not None:
            lots = [l for l in lots if l.expires is None or l.expires > now]
        return sorted(lots, key=fefo_key)

    def on_hand(self, sku, now=None):
        return sum(l.qty for l in self.lots_for(sku, now))

    def snapshot(self):
        """``{lot id: qty}`` for every lot (including empty ones)."""
        return {lot_id: lot.qty for lot_id, lot in sorted(self._lots.items())}

    # -- availability ------------------------------------------------------
    def available(self, sku, now):
        """Sellable units: usable stock minus the reservations that are active at ``now``."""
        return max(0, self.on_hand(sku, now) - self.book.reserved_qty(sku))

    # -- planning and committing -------------------------------------------
    def plan(self, sku, qty, now, taken=None):
        """Which lots would serve ``qty`` units, as ``[(lot_id, units)]``; nothing is changed.

        ``taken`` maps lot id -> units already promised to earlier lines of the same order;
        those units are not available again.  Raises InsufficientStock.
        """
        if qty <= 0:
            raise WarehouseError("quantity must be positive")
        sellable = self.available(sku, now)
        if sellable < qty:
            raise InsufficientStock(sku, qty, max(0, sellable))
        remaining = qty
        picks = []
        for lot in self.lots_for(sku, now):
            free = lot.qty
            if free <= 0:
                continue
            take = min(free, remaining)
            picks.append((lot.id, take))
            remaining -= take
            if remaining == 0:
                break
        if remaining:
            raise InsufficientStock(sku, qty, qty - remaining)
        return picks

    def commit(self, picks):
        """Take the planned units out of their lots."""
        for lot_id, units in picks:
            lot = self.lot(lot_id)
            if lot.qty < units:
                raise WarehouseError("lot %s cannot give %d units" % (lot_id, units))
        for lot_id, units in picks:
            self.lot(lot_id).qty -= units

    def restore(self, lot_id, units):
        """Put units back into the lot they came from."""
        self.lot(lot_id).qty += units
