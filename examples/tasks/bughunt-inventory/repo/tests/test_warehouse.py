import unittest
from decimal import Decimal as Dec

from warehouse import (AuditLog, Catalog, InsufficientStock, OrderError, OrderService, Product, ReservationBook, Stock,
                       UnknownProduct, expiring_soon, reorder_report, shipping_cost, valuation)
from warehouse.money import fmt, percent_of, round_cents
from warehouse.pricing import price_line, tier_percent


def make():
    catalog = Catalog()
    catalog.add(Product("A100", "Widget", "10.00", "0.5", True, [(10, "5"), (50, "10")]))
    catalog.add(Product("B200", "Gadget", "25.50", "2"))
    stock = Stock()
    stock.add_lot("L1", "A100", 10, received=1, expires=30)
    stock.add_lot("L2", "A100", 20, received=2, expires=20)
    stock.add_lot("L4", "B200", 4, received=1)
    return catalog, stock


class StockTests(unittest.TestCase):
    def test_fefo_order(self):
        _, stock = make()
        self.assertEqual([l.id for l in stock.lots_for("A100")], ["L2", "L1"])
        self.assertEqual(stock.plan("A100", 25, now=5), [("L2", 20), ("L1", 5)])

    def test_expired_lots_unusable(self):
        _, stock = make()
        self.assertEqual([l.id for l in stock.lots_for("A100", now=20)], ["L1"])
        self.assertEqual(stock.on_hand("A100", now=20), 10)

    def test_insufficient(self):
        _, stock = make()
        with self.assertRaises(InsufficientStock) as cm:
            stock.plan("B200", 5, now=0)
        self.assertEqual((cm.exception.sku, cm.exception.available), ("B200", 4))


class MoneyAndPricingTests(unittest.TestCase):
    def test_rounding(self):
        self.assertEqual(round_cents("1.234"), Dec("1.23"))
        self.assertEqual(round_cents("1.236"), Dec("1.24"))
        self.assertEqual(percent_of("200.00", "12.5"), Dec("25.00"))
        self.assertEqual(fmt(Dec("1234.5")), "1,234.50")

    def test_tiers_and_tax(self):
        catalog, _ = make()
        widget = catalog.get("A100")
        self.assertEqual(tier_percent(widget, 5), 0)
        self.assertEqual(tier_percent(widget, 12), Dec("5"))
        self.assertEqual(tier_percent(widget, 60), Dec("10"))
        line = price_line(widget, 12, "0.10")
        self.assertEqual((line.gross, line.discount, line.net, line.tax), (Dec("120.00"), Dec("6.00"), Dec("114.00"), Dec("11.40")))


class ShippingTests(unittest.TestCase):
    def test_brackets(self):
        self.assertEqual(shipping_cost("0"), Dec("0.00"))
        self.assertEqual(shipping_cost("0.5"), Dec("5.00"))
        self.assertEqual(shipping_cost("3"), Dec("9.50"))
        self.assertEqual(shipping_cost("12.5"), Dec("18.00"))
        self.assertEqual(shipping_cost("21.5"), Dec("20.40"))


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.catalog, self.stock = make()
        self.service = OrderService(self.catalog, self.stock, tax_rate="0.10")

    def test_place_totals(self):
        order = self.service.place([("A100", 12), ("B200", 2)], now=5)
        self.assertEqual(order.id, "O1")
        self.assertEqual(order.totals["net"], Dec("165.00"))
        self.assertEqual(order.totals["tax"], Dec("16.50"))
        self.assertEqual(order.shipping, Dec("18.00"))
        self.assertEqual(order.allocations, [("A100", "L2", 12), ("B200", "L4", 2)])

    def test_atomic_failure(self):
        before = self.stock.snapshot()
        with self.assertRaises(InsufficientStock):
            self.service.place([("A100", 5), ("B200", 9)], now=5)
        self.assertEqual(self.stock.snapshot(), before)
        self.assertEqual(len(self.service.audit), 0)

    def test_validation(self):
        for lines in ([], [("A100", 0)], [("A100", True)], [("A100", -1)]):
            with self.assertRaises(OrderError):
                self.service.place(lines, now=1)
        with self.assertRaises(UnknownProduct):
            self.service.place([("ZZZ", 1)], now=1)

    def test_cancel_single_lot(self):
        before = self.stock.snapshot()
        order = self.service.place([("A100", 5)], now=5)
        self.service.cancel(order.id)
        self.assertEqual(self.stock.snapshot(), before)
        with self.assertRaises(OrderError):
            self.service.cancel(order.id)


class ReportTests(unittest.TestCase):
    def test_reports(self):
        catalog, stock = make()
        rows = reorder_report(stock, {"A100": 40, "B200": 10, "ZZZ": 0})
        self.assertEqual([(r.sku, r.shortfall) for r in rows], [("A100", 10), ("B200", 6)])
        self.assertEqual([l.id for l in expiring_soon(stock, 15, 10)], ["L2"])
        per_sku, total = valuation(stock, catalog)
        self.assertEqual((per_sku["A100"], total), (Dec("300.00"), Dec("402.00")))

    def test_reservations(self):
        _, stock = make()
        stock.book.reserve("B200", 3, expires_at=10)
        self.assertEqual(stock.available("B200", 5), 1)


if __name__ == "__main__":
    unittest.main()
