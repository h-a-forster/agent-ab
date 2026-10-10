"""Customer returns."""

from decimal import Decimal

from .errors import OrderError
from .money import round_cents


class ReturnResult:
    def __init__(self, sku, qty, refund, restocked):
        self.sku = sku
        self.qty = qty
        self.refund = refund
        self.restocked = restocked  # list of (lot_id, units)

    def __repr__(self):
        return "ReturnResult(%s x%d refund=%s)" % (self.sku, self.qty, self.refund)


class ReturnService:
    def __init__(self, orders, stock, audit=None):
        self.orders = orders
        self.stock = stock
        self.audit = audit if audit is not None else orders.audit
        self._returned = {}

    def returned_qty(self, order_id, sku):
        return self._returned.get((order_id, sku), 0)

    def return_items(self, order_id, sku, qty):
        """Take back ``qty`` units of ``sku``.

        The refund is the line's net price and tax in proportion to the returned share, each
        rounded to cents.  Units go back to the lots they were taken from, last pick first.
        """
        order = self.orders.get(order_id)
        if order.status != "placed":
            raise OrderError("order %s is %s" % (order_id, order.status))
        line = next((l for l in order.lines if l.sku == sku), None)
        if line is None:
            raise OrderError("order %s has no line for %s" % (order_id, sku))
        already = self.returned_qty(order_id, sku)
        if qty <= 0 or already + qty > line.qty:
            raise OrderError("cannot return %d of %s (bought %d, returned %d)" % (qty, sku, line.qty, already))
        share = Decimal(qty) / Decimal(line.qty)
        refund = round_cents(line.net * share) + round_cents(line.tax * share)
        remaining = qty
        restocked = []
        picks = [(lot_id, units) for s, lot_id, units in order.allocations if s == sku]
        for lot_id, units in reversed(picks):
            if remaining == 0:
                break
            back = min(units, remaining)
            self.stock.restore(lot_id, back)
            restocked.append((lot_id, back))
            remaining -= back
        self._returned[(order_id, sku)] = already + qty
        self.audit.log("items_returned", order=order_id, sku=sku, qty=qty, refund=str(refund))
        return ReturnResult(sku, qty, refund, restocked)
