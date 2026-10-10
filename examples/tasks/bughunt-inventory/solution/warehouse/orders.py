"""Placing and cancelling orders."""

from decimal import Decimal

from . import pricing, shipping
from .audit import AuditLog
from .errors import InsufficientStock, OrderError
from .money import to_decimal


class Order:
    def __init__(self, order_id, placed_at, lines, allocations, totals, shipping_cost):
        self.id = order_id
        self.placed_at = placed_at
        self.lines = lines  # list of PricedLine
        self.allocations = allocations  # list of (sku, lot_id, units)
        self.totals = totals
        self.shipping = shipping_cost
        self.status = "placed"

    @property
    def grand_total(self):
        return self.totals["total"] + self.shipping

    def __repr__(self):
        return "Order(%s %s)" % (self.id, self.status)


class OrderService:
    def __init__(self, catalog, stock, tax_rate="0.10", free_shipping_over=None, audit=None):
        self.catalog = catalog
        self.stock = stock
        self.tax_rate = to_decimal(tax_rate)
        self.free_shipping_over = free_shipping_over
        self.audit = audit if audit is not None else AuditLog()
        self._orders = {}
        self._next = 1

    def get(self, order_id):
        try:
            return self._orders[order_id]
        except KeyError:
            raise OrderError("unknown order %s" % order_id) from None

    def place(self, lines, now):
        """Place an order for ``[(sku, qty), ...]`` (a SKU may appear on several lines).

        All lines are planned before anything is taken: if any line cannot be served the
        stock is left untouched and InsufficientStock is raised.
        """
        if not lines:
            raise OrderError("an order needs at least one line")
        taken = {}
        planned = []
        for sku, qty in lines:
            if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
                raise OrderError("bad quantity for %s: %r" % (sku, qty))
            product = self.catalog.get(sku)
            picks = self.stock.plan(sku, qty, now, taken)
            for lot_id, units in picks:
                taken[lot_id] = taken.get(lot_id, 0) + units
            planned.append((product, qty, picks))

        priced = [pricing.price_line(product, qty, self.tax_rate) for product, qty, _ in planned]
        totals = pricing.sum_lines(priced)
        weight = sum((product.weight_kg * qty for product, qty, _ in planned), Decimal(0))
        cost = shipping.apply_free_shipping(shipping.shipping_cost(weight), totals["net"], self.free_shipping_over)

        allocations = []
        for product, _, picks in planned:
            self.stock.commit(picks)
            allocations.extend((product.sku, lot_id, units) for lot_id, units in picks)

        order = Order("O%d" % self._next, now, priced, allocations, totals, cost)
        self._next += 1
        self._orders[order.id] = order
        self.audit.log("order_placed", order=order.id, total=str(order.grand_total))
        return order

    def cancel(self, order_id):
        """Cancel a placed order and put every unit back into the lot it was taken from."""
        order = self.get(order_id)
        if order.status != "placed":
            raise OrderError("order %s is %s" % (order_id, order.status))
        for _, lot_id, units in order.allocations:
            self.stock.restore(lot_id, units)
        order.status = "cancelled"
        self.audit.log("order_cancelled", order=order.id)
        return order

    def orders(self, status=None):
        return [o for o in self._orders.values() if status is None or o.status == status]
