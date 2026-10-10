import unittest
from decimal import Decimal as Dec

from warehouse import (AuditLog, Catalog, InsufficientStock, OrderError, OrderService, Product, ReservationBook,
                       ReservationError, ReturnService, Stock, UnknownProduct, WarehouseError, apply_count,
                       expiring_soon, reorder_report, shipping_cost, stock_levels, valuation, write_off_expired)
from warehouse.adjustments import shrinkage
from warehouse.forecast import days_of_cover, daily_demand, demand_from_orders, suggest_order_qty
from warehouse.invoice import packing_slip, render_invoice
from warehouse.money import fmt, percent_of, round_cents, to_decimal
from warehouse.pricing import price_line, sum_lines, tier_percent
from warehouse.shipping import apply_free_shipping, surcharge
from warehouse.stock import fefo_key


def make(tax="0.10", **kw):
    catalog = Catalog()
    catalog.add(Product("A100", "Widget", "10.00", "0.5", True, [(10, "5"), (50, "10")]))
    catalog.add(Product("B200", "Gadget", "25.50", "2"))
    catalog.add(Product("C300", "Tea", "4.00", "0.2", False, [(5, "10")]))
    catalog.add(Product("D400", "Anvil", "99.99", "12.5"))
    catalog.add(Product("E500", "Sticker", "0.25", "0"))
    catalog.add(Product("F600", "Pin", "0.50", "0", True, [(1, "5")]))
    stock = Stock()
    stock.add_lot("L1", "A100", 10, received=1, expires=30)
    stock.add_lot("L2", "A100", 20, received=2, expires=20)
    stock.add_lot("L3", "A100", 5, received=0, expires=None)
    stock.add_lot("L4", "B200", 4, received=1)
    stock.add_lot("L5", "C300", 6, received=3, expires=10)
    stock.add_lot("L6", "C300", 6, received=1, expires=10)
    stock.add_lot("L7", "D400", 3, received=1)
    stock.add_lot("L8", "E500", 100, received=1)
    stock.add_lot("L9", "F600", 100, received=1)
    service = OrderService(catalog, stock, tax_rate=tax, **kw)
    return catalog, stock, service


class FefoSymptoms(unittest.TestCase):
    def test_never_expiring_lot_is_last(self):
        _, stock, _ = make()
        self.assertEqual([l.id for l in stock.lots_for("A100")], ["L2", "L1", "L3"])

    def test_plan_prefers_expiring_stock(self):
        _, stock, _ = make()
        self.assertEqual(stock.plan("A100", 25, now=5), [("L2", 20), ("L1", 5)])
        self.assertEqual(stock.plan("A100", 33, now=5), [("L2", 20), ("L1", 10), ("L3", 3)])
        self.assertEqual(stock.plan("A100", 2, now=5), [("L2", 2)])

    def test_order_allocations(self):
        _, stock, service = make()
        order = service.place([("A100", 12)], now=5)
        self.assertEqual(order.allocations, [("A100", "L2", 12)])
        order = service.place([("A100", 12)], now=5)
        self.assertEqual(order.allocations, [("A100", "L2", 8), ("A100", "L1", 4)])
        self.assertEqual(stock.snapshot()["L3"], 5)

    def test_expired_lot_skipped_then_non_perishable(self):
        _, stock, _ = make()
        self.assertEqual([l.id for l in stock.lots_for("A100", now=25)], ["L1", "L3"])
        self.assertEqual(stock.plan("A100", 12, now=25), [("L1", 10), ("L3", 2)])

    def test_ties_and_key(self):
        _, stock, _ = make()
        self.assertEqual([l.id for l in stock.lots_for("C300")], ["L6", "L5"])
        stock.add_lot("L10", "C300", 1, received=1, expires=10)
        self.assertEqual([l.id for l in stock.lots_for("C300")], ["L10", "L6", "L5"])
        stock.add_lot("L11", "C300", 1, received=0, expires=None)
        self.assertEqual([l.id for l in stock.lots_for("C300")][-1], "L11")
        self.assertTrue(fefo_key(stock.lot("L11")) > fefo_key(stock.lot("L5")))

    def test_only_non_perishable_still_works(self):
        _, stock, _ = make()
        self.assertEqual(stock.plan("B200", 3, now=0), [("L4", 3)])
        stock.add_lot("L12", "B200", 5, received=0)
        self.assertEqual([l.id for l in stock.lots_for("B200")], ["L12", "L4"])

    def test_zero_expiry_day_is_a_real_date(self):
        _, stock, _ = make()
        stock.add_lot("L13", "B200", 1, received=0, expires=0)
        self.assertEqual([l.id for l in stock.lots_for("B200", now=-1)][0], "L13")
        self.assertEqual([l.id for l in stock.lots_for("B200", now=0)], ["L4"])


class OversellSymptoms(unittest.TestCase):
    def test_same_sku_two_lines_beyond_stock(self):
        _, stock, service = make()
        before = stock.snapshot()
        with self.assertRaises(InsufficientStock) as cm:
            service.place([("B200", 3), ("B200", 3)], now=1)
        self.assertEqual(cm.exception.sku, "B200")
        self.assertEqual(stock.snapshot(), before)
        self.assertEqual(len(service.audit), 0)
        self.assertEqual(service.orders(), [])

    def test_same_sku_two_lines_within_stock(self):
        _, stock, service = make()
        order = service.place([("B200", 2), ("B200", 2)], now=1)
        self.assertEqual(order.allocations, [("B200", "L4", 2), ("B200", "L4", 2)])
        self.assertEqual(stock.lot("L4").qty, 0)
        self.assertEqual(stock.on_hand("B200"), 0)

    def test_multi_lot_split_lines(self):
        _, stock, service = make()
        order = service.place([("A100", 15), ("A100", 15)], now=5)
        self.assertEqual(order.allocations, [("A100", "L2", 15), ("A100", "L2", 5), ("A100", "L1", 10)])
        self.assertEqual(stock.snapshot()["L2"], 0)
        self.assertEqual(stock.snapshot()["L1"], 0)
        with self.assertRaises(InsufficientStock):
            service.place([("A100", 6)], now=5)

    def test_total_over_on_hand_across_lines(self):
        _, stock, service = make()
        before = stock.snapshot()
        with self.assertRaises(InsufficientStock):
            service.place([("A100", 20), ("A100", 10), ("A100", 6)], now=5)
        self.assertEqual(stock.snapshot(), before)
        order = service.place([("A100", 20), ("A100", 10), ("A100", 5)], now=5)
        self.assertEqual(sum(units for _, _, units in order.allocations), 35)
        self.assertEqual(stock.on_hand("A100"), 0)

    def test_plan_with_taken(self):
        _, stock, _ = make()
        self.assertEqual(stock.plan("A100", 10, now=5, taken={"L2": 20}), [("L1", 10)])
        with self.assertRaises(InsufficientStock) as cm:
            stock.plan("B200", 3, now=1, taken={"L4": 2})
        self.assertEqual(cm.exception.available, 2)
        self.assertEqual(stock.plan("B200", 2, now=1, taken={"L4": 2}), [("L4", 2)])

    def test_interleaved_skus(self):
        _, stock, service = make()
        order = service.place([("B200", 2), ("A100", 1), ("B200", 2), ("A100", 1)], now=1)
        self.assertEqual([a[0] for a in order.allocations], ["B200", "A100", "B200", "A100"])
        self.assertEqual(stock.lot("L4").qty, 0)
        self.assertEqual(stock.lot("L2").qty, 18)

    def test_reservations_count_once(self):
        _, stock, service = make()
        stock.book.reserve("B200", 1, expires_at=50)
        with self.assertRaises(InsufficientStock):
            service.place([("B200", 2), ("B200", 2)], now=1)
        order = service.place([("B200", 2), ("B200", 1)], now=1)
        self.assertEqual(sum(u for _, _, u in order.allocations), 3)


class TierSymptoms(unittest.TestCase):
    def test_exact_threshold_qualifies(self):
        catalog, _, _ = make()
        widget = catalog.get("A100")
        self.assertEqual(tier_percent(widget, 9), 0)
        self.assertEqual(tier_percent(widget, 10), Dec("5"))
        self.assertEqual(tier_percent(widget, 49), Dec("5"))
        self.assertEqual(tier_percent(widget, 50), Dec("10"))
        self.assertEqual(tier_percent(widget, 51), Dec("10"))

    def test_price_line_at_threshold(self):
        catalog, _, _ = make()
        line = price_line(catalog.get("A100"), 10, "0.10")
        self.assertEqual((line.gross, line.discount, line.net, line.tax, line.total),
                         (Dec("100.00"), Dec("5.00"), Dec("95.00"), Dec("9.50"), Dec("104.50")))
        line = price_line(catalog.get("A100"), 50, "0.10")
        self.assertEqual((line.discount, line.net), (Dec("50.00"), Dec("450.00")))
        line = price_line(catalog.get("A100"), 9, "0.10")
        self.assertEqual((line.discount, line.net), (Dec("0.00"), Dec("90.00")))

    def test_other_product_and_order(self):
        catalog, stock, service = make()
        line = price_line(catalog.get("C300"), 5, "0.10")
        self.assertEqual((line.gross, line.discount, line.net, line.tax), (Dec("20.00"), Dec("2.00"), Dec("18.00"), Dec("0.00")))
        order = service.place([("A100", 10)], now=5)
        self.assertEqual(order.totals, {"gross": Dec("100.00"), "discount": Dec("5.00"), "net": Dec("95.00"),
                                        "tax": Dec("9.50"), "total": Dec("104.50")})

    def test_threshold_one(self):
        catalog, _, _ = make()
        self.assertEqual(tier_percent(catalog.get("F600"), 1), Dec("5"))
        self.assertEqual(tier_percent(catalog.get("F600"), 0), 0)


class RoundingSymptoms(unittest.TestCase):
    def test_round_cents_halves_away_from_zero(self):
        cases = {"0.005": "0.01", "0.015": "0.02", "0.025": "0.03", "0.035": "0.04", "0.045": "0.05", "-0.005": "-0.01",
                 "-0.025": "-0.03", "2.675": "2.68", "1.005": "1.01", "0.004": "0.00", "0.994": "0.99"}
        for text, expected in cases.items():
            self.assertEqual(round_cents(text), Dec(expected), text)

    def test_percent_of(self):
        self.assertEqual(percent_of("0.20", "12.5"), Dec("0.03"))
        self.assertEqual(percent_of("0.25", "10"), Dec("0.03"))
        self.assertEqual(percent_of("10.50", "12.5"), Dec("1.31"))
        self.assertEqual(percent_of("200.00", "12.5"), Dec("25.00"))

    def test_tax_rounding(self):
        catalog, _, _ = make()
        line = price_line(catalog.get("E500"), 1, "0.10")
        self.assertEqual((line.net, line.tax), (Dec("0.25"), Dec("0.03")))

    def test_discount_rounding(self):
        catalog, _, _ = make()
        line = price_line(catalog.get("F600"), 1, "0.00")
        self.assertEqual((line.gross, line.discount, line.net), (Dec("0.50"), Dec("0.03"), Dec("0.47")))

    def test_surcharge(self):
        self.assertEqual(surcharge(Dec("5.00"), "0.5"), Dec("5.03"))
        self.assertEqual(surcharge(Dec("18.00"), "10"), Dec("19.80"))

    def test_order_with_half_cents(self):
        _, stock, service = make()
        order = service.place([("E500", 1), ("F600", 1)], now=1)
        self.assertEqual(order.totals["tax"], Dec("0.03") + Dec("0.05"))
        self.assertEqual(order.totals["discount"], Dec("0.03"))

    def test_refund_rounding(self):
        _, stock, service = make()
        order = service.place([("E500", 3)], now=1)
        self.assertEqual((order.lines[0].net, order.lines[0].tax), (Dec("0.75"), Dec("0.08")))
        returns = ReturnService(service, stock)
        result = returns.return_items(order.id, "E500", 1)
        self.assertEqual(result.refund, Dec("0.25") + Dec("0.03"))


class ShippingSymptoms(unittest.TestCase):
    def test_limits_belong_to_their_bracket(self):
        cases = {"1": "5.00", "5": "9.50", "20": "18.00", "1.0": "5.00", "5.00": "9.50", "20.0": "18.00"}
        for weight, cost in cases.items():
            self.assertEqual(shipping_cost(weight), Dec(cost), weight)

    def test_just_above_limits(self):
        cases = {"0.01": "5.00", "0.99": "5.00", "1.01": "9.50", "4.99": "9.50", "5.01": "18.00", "19.99": "18.00",
                 "20.01": "19.20", "21": "19.20", "21.01": "20.40", "25": "24.00", "0": "0.00"}
        for weight, cost in cases.items():
            self.assertEqual(shipping_cost(weight), Dec(cost), weight)

    def test_order_exactly_at_limit(self):
        _, _, service = make()
        order = service.place([("A100", 10)], now=5)
        self.assertEqual(order.shipping, Dec("9.50"))
        order = service.place([("C300", 5)], now=5)
        self.assertEqual(order.shipping, Dec("5.00"))

    def test_heavy_order(self):
        _, _, service = make()
        order = service.place([("D400", 2)], now=1)
        self.assertEqual(order.shipping, Dec("18.00") + Dec("1.20") * 5)

    def test_free_shipping_threshold_inclusive(self):
        self.assertEqual(apply_free_shipping(Dec("9.50"), "50.00", "50.00"), Dec("0.00"))
        self.assertEqual(apply_free_shipping(Dec("9.50"), "49.99", "50.00"), Dec("9.50"))
        self.assertEqual(apply_free_shipping(Dec("9.50"), "500", None), Dec("9.50"))
        _, _, service = make(free_shipping_over="95.00")
        order = service.place([("A100", 10)], now=5)
        self.assertEqual(order.shipping, Dec("0.00"))
        self.assertEqual(order.grand_total, Dec("104.50"))


class ReservationSymptoms(unittest.TestCase):
    def test_expired_reservation_does_not_block(self):
        _, stock, _ = make()
        stock.book.reserve("B200", 3, expires_at=10)
        self.assertEqual(stock.available("B200", 9), 1)
        self.assertEqual(stock.available("B200", 10), 4)
        self.assertEqual(stock.available("B200", 11), 4)
        self.assertEqual(stock.available("B200", 100), 4)

    def test_without_purge(self):
        _, stock, _ = make()
        stock.book.reserve("B200", 2, expires_at=5)
        stock.book.reserve("B200", 1, expires_at=20)
        self.assertEqual(stock.available("B200", 4), 1)
        self.assertEqual(stock.available("B200", 6), 3)
        self.assertEqual(stock.available("B200", 20), 4)
        self.assertEqual(len(stock.book), 2)

    def test_orders_after_expiry(self):
        _, stock, service = make()
        stock.book.reserve("B200", 4, expires_at=10)
        with self.assertRaises(InsufficientStock):
            service.place([("B200", 1)], now=9)
        order = service.place([("B200", 4)], now=10)
        self.assertEqual(order.allocations, [("B200", "L4", 4)])

    def test_plan_and_levels(self):
        catalog, stock, _ = make()
        stock.book.reserve("B200", 3, expires_at=10)
        with self.assertRaises(InsufficientStock) as cm:
            stock.plan("B200", 2, now=9)
        self.assertEqual(cm.exception.available, 1)
        self.assertEqual(stock.plan("B200", 4, now=12), [("L4", 4)])
        rows = {r[0]: r for r in stock_levels(stock, catalog, 12)}
        self.assertEqual(rows["B200"], ("B200", 4, 0, 4))
        rows = {r[0]: r for r in stock_levels(stock, catalog, 5)}
        self.assertEqual(rows["B200"], ("B200", 4, 3, 1))

    def test_reservation_book_itself(self):
        book = ReservationBook()
        r = book.reserve("X", 2, 10)
        self.assertEqual(book.reserved_qty("X", 9), 2)
        self.assertEqual(book.reserved_qty("X", 10), 0)
        self.assertEqual(book.reserved_qty("X"), 2)
        self.assertEqual(book.purge(10), 1)
        self.assertEqual(book.reserved_qty("X"), 0)
        with self.assertRaises(ReservationError):
            book.release(r.id)


class CancelSymptoms(unittest.TestCase):
    def test_units_return_to_original_lots(self):
        _, stock, service = make()
        before = stock.snapshot()
        order = service.place([("A100", 25)], now=5)
        self.assertEqual(stock.snapshot()["L2"], 0)
        service.cancel(order.id)
        self.assertEqual(stock.snapshot(), before)

    def test_multiple_orders_and_skus(self):
        _, stock, service = make()
        first = service.place([("A100", 25), ("B200", 3)], now=5)
        mid = stock.snapshot()
        second = service.place([("A100", 6), ("C300", 8)], now=5)
        service.cancel(first.id)
        after = stock.snapshot()
        self.assertEqual(after["L2"], 20)
        service.cancel(second.id)
        self.assertEqual(stock.snapshot(), {"L1": 10, "L2": 20, "L3": 5, "L4": 4, "L5": 6, "L6": 6, "L7": 3, "L8": 100, "L9": 100})
        self.assertEqual(mid["L4"], 1)

    def test_cancel_when_other_lots_exist(self):
        _, stock, service = make()
        order = service.place([("C300", 8)], now=1)
        self.assertEqual(order.allocations, [("C300", "L6", 6), ("C300", "L5", 2)])
        service.cancel(order.id)
        self.assertEqual((stock.lot("L5").qty, stock.lot("L6").qty), (6, 6))

    def test_cancel_state_and_audit(self):
        _, stock, service = make()
        order = service.place([("B200", 1)], now=1)
        service.cancel(order.id)
        self.assertEqual(order.status, "cancelled")
        self.assertEqual([e.kind for e in service.audit.events()], ["order_placed", "order_cancelled"])
        with self.assertRaises(OrderError):
            service.cancel(order.id)
        with self.assertRaises(OrderError):
            service.cancel("O99")

    def test_cancel_restores_even_empty_lots_while_others_have_stock(self):
        _, stock, service = make()
        order = service.place([("A100", 20)], now=5)
        self.assertEqual(stock.lot("L2").qty, 0)
        service.cancel(order.id)
        self.assertEqual(stock.lot("L2").qty, 20)
        self.assertEqual(stock.lot("L1").qty, 10)


class MoneyRegression(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(to_decimal(5), Dec("5"))
        self.assertEqual(to_decimal("1.50"), Dec("1.50"))
        with self.assertRaises(TypeError):
            to_decimal(1.5)
        self.assertEqual(fmt(Dec("1234567.891")), "1,234,567.89")
        self.assertEqual(fmt("0.5"), "0.50")
        self.assertEqual(round_cents("2"), Dec("2.00"))
        self.assertEqual(round_cents("-1.234"), Dec("-1.23"))
        self.assertEqual(percent_of("100", "0"), Dec("0.00"))


class CatalogRegression(unittest.TestCase):
    def test_catalog(self):
        catalog, _, _ = make()
        self.assertEqual(catalog.skus(), ["A100", "B200", "C300", "D400", "E500", "F600"])
        self.assertIn("A100", catalog)
        with self.assertRaises(UnknownProduct):
            catalog.get("NOPE")
        with self.assertRaises(WarehouseError):
            catalog.add(Product("A100", "dup", "1"))
        for kwargs in ({"unit_price": "-1"}, {"unit_price": "1", "weight_kg": "-1"}, {"unit_price": "1", "tiers": [(1, "101")]}):
            with self.assertRaises(WarehouseError):
                Product("X", "x", **kwargs)

    def test_tiers_sorted(self):
        p = Product("X", "x", "1", tiers=[(50, "10"), (10, "5")])
        self.assertEqual(tier_percent(p, 20), Dec("5"))
        self.assertEqual(tier_percent(p, 100), Dec("10"))
        self.assertEqual(tier_percent(Product("Y", "y", "1"), 5), 0)


class StockRegression(unittest.TestCase):
    def test_lots(self):
        _, stock, _ = make()
        self.assertEqual(stock.on_hand("A100"), 35)
        self.assertEqual(stock.on_hand("A100", now=25), 15)
        self.assertEqual(stock.on_hand("NOPE"), 0)
        with self.assertRaises(WarehouseError):
            stock.add_lot("L1", "A100", 1, 1)
        with self.assertRaises(WarehouseError):
            stock.add_lot("LX", "A100", -1, 1)
        with self.assertRaises(WarehouseError):
            stock.lot("nope")
        with self.assertRaises(WarehouseError):
            stock.plan("A100", 0, now=1)

    def test_commit_and_restore(self):
        _, stock, _ = make()
        picks = stock.plan("A100", 25, now=5)
        stock.commit(picks)
        self.assertEqual((stock.lot("L2").qty, stock.lot("L1").qty), (0, 5))
        stock.restore("L2", 20)
        self.assertEqual(stock.lot("L2").qty, 20)
        with self.assertRaises(WarehouseError):
            stock.commit([("L4", 5)])
        self.assertEqual(stock.lot("L4").qty, 4)

    def test_empty_lots_not_listed(self):
        _, stock, _ = make()
        stock.commit(stock.plan("B200", 4, now=1))
        self.assertEqual(stock.lots_for("B200"), [])
        self.assertEqual(stock.snapshot()["L4"], 0)
        with self.assertRaises(InsufficientStock):
            stock.plan("B200", 1, now=1)

    def test_available_never_negative(self):
        _, stock, _ = make()
        stock.book.reserve("B200", 10, expires_at=100)
        self.assertEqual(stock.available("B200", 1), 0)


class OrderRegression(unittest.TestCase):
    def test_full_order_numbers(self):
        _, stock, service = make()
        order = service.place([("A100", 12), ("B200", 2), ("C300", 1)], now=5)
        self.assertEqual([(l.sku, l.net, l.tax) for l in order.lines],
                         [("A100", Dec("114.00"), Dec("11.40")), ("B200", Dec("51.00"), Dec("5.10")), ("C300", Dec("4.00"), Dec("0.00"))])
        self.assertEqual(order.totals["total"], Dec("185.50"))
        self.assertEqual(order.shipping, Dec("18.00"))
        self.assertEqual(order.grand_total, Dec("203.50"))
        self.assertEqual(order.placed_at, 5)
        self.assertEqual(service.audit.last("order_placed").data["total"], "203.50")

    def test_ids_and_queries(self):
        _, _, service = make()
        a = service.place([("B200", 1)], now=1)
        b = service.place([("B200", 1)], now=2)
        self.assertEqual((a.id, b.id), ("O1", "O2"))
        service.cancel(a.id)
        self.assertEqual([o.id for o in service.orders("placed")], ["O2"])
        self.assertEqual([o.id for o in service.orders()], ["O1", "O2"])
        self.assertIs(service.get("O2"), b)

    def test_validation_leaves_nothing_behind(self):
        _, stock, service = make()
        before = stock.snapshot()
        for lines in ([("B200", 1), ("B200", 0)], [("B200", 1), ("ZZZ", 1)], [("B200", 1), ("D400", 4)]):
            with self.assertRaises(Exception):
                service.place(lines, now=1)
            self.assertEqual(stock.snapshot(), before)
        self.assertEqual(len(service.audit), 0)

    def test_sum_lines_empty(self):
        self.assertEqual(sum_lines([]), {"gross": Dec("0.00"), "discount": Dec("0.00"), "net": Dec("0.00"),
                                         "tax": Dec("0.00"), "total": Dec("0.00")})

    def test_tax_rate_override(self):
        _, _, service = make(tax="0.085")
        order = service.place([("B200", 2)], now=1)
        self.assertEqual(order.lines[0].tax, Dec("4.34"))


class ReportRegression(unittest.TestCase):
    def test_reorder_sorting(self):
        _, stock, _ = make()
        rows = reorder_report(stock, {"A100": 45, "B200": 14, "C300": 22, "D400": 3, "E500": 120, "F600": 110})
        self.assertEqual([r.sku for r in rows], ["E500", "A100", "B200", "C300", "F600"])
        self.assertEqual([r.shortfall for r in rows], [20, 10, 10, 10, 10])

    def test_reorder_now(self):
        _, stock, _ = make()
        rows = reorder_report(stock, {"A100": 35}, now=25)
        self.assertEqual([(r.sku, r.on_hand, r.shortfall) for r in rows], [("A100", 15, 20)])

    def test_expiring_soon(self):
        _, stock, _ = make()
        self.assertEqual([l.id for l in expiring_soon(stock, 5, 5)], ["L5", "L6"])
        self.assertEqual([l.id for l in expiring_soon(stock, 5, 15)], ["L5", "L6", "L2"])
        self.assertEqual([l.id for l in expiring_soon(stock, 11, 100)], ["L2", "L1"])
        self.assertEqual(expiring_soon(stock, 0, 0), [])

    def test_valuation(self):
        catalog, stock, _ = make()
        per_sku, total = valuation(stock, catalog)
        self.assertEqual(per_sku["A100"], Dec("350.00"))
        self.assertEqual(total, Dec("350.00") + Dec("102.00") + Dec("48.00") + Dec("299.97") + Dec("25.00") + Dec("50.00"))
        per_sku, total = valuation(stock, catalog, now=25)
        self.assertEqual(per_sku["A100"], Dec("150.00"))
        self.assertNotIn("C300", per_sku)


class InvoiceReturnRegression(unittest.TestCase):
    def test_invoice(self):
        catalog, _, service = make()
        order = service.place([("A100", 12), ("B200", 2)], now=5)
        text = render_invoice(order, catalog)
        self.assertEqual(text.split("\n"), [
            "Invoice for order O1", "",
            "Widget  x12      114.00  (-6.00)", "Gadget  x2        51.00", "",
            "Subtotal         165.00", "Tax               16.50", "Shipping          18.00", "Total            199.50"])

    def test_packing_slip(self):
        _, _, service = make()
        order = service.place([("A100", 25), ("B200", 1)], now=5)
        self.assertEqual(packing_slip(order), "Packing slip for order O1\nA100\n  L2 x20\n  L1 x5\nB200\n  L4 x1")

    def test_returns(self):
        _, stock, service = make()
        order = service.place([("A100", 12)], now=5)
        returns = ReturnService(service, stock)
        result = returns.return_items(order.id, "A100", 3)
        self.assertEqual(result.refund, Dec("28.50") + Dec("2.85"))
        self.assertEqual(result.restocked, [("L2", 3)])
        self.assertEqual(stock.lot("L2").qty, 11)
        self.assertEqual(returns.returned_qty(order.id, "A100"), 3)
        with self.assertRaises(OrderError):
            returns.return_items(order.id, "A100", 10)
        with self.assertRaises(OrderError):
            returns.return_items(order.id, "B200", 1)
        with self.assertRaises(OrderError):
            returns.return_items(order.id, "A100", 0)

    def test_returns_span_lots_last_pick_first(self):
        _, stock, service = make()
        order = service.place([("A100", 25)], now=5)
        returns = ReturnService(service, stock)
        result = returns.return_items(order.id, "A100", 7)
        self.assertEqual(result.restocked, [("L1", 5), ("L2", 2)])
        self.assertEqual((stock.lot("L1").qty, stock.lot("L2").qty), (10, 2))

    def test_return_after_cancel(self):
        _, stock, service = make()
        order = service.place([("B200", 2)], now=5)
        service.cancel(order.id)
        with self.assertRaises(OrderError):
            ReturnService(service, stock).return_items(order.id, "B200", 1)


class ForecastAdjustRegression(unittest.TestCase):
    def test_forecast(self):
        self.assertEqual(daily_demand([(1, 4), (3, 6), (5, 10)], 5), 4.0)
        self.assertEqual(daily_demand([(1, 4), (3, 6), (5, 10)], 3), 16 / 3)
        self.assertEqual(daily_demand([], 7), 0.0)
        self.assertEqual(days_of_cover(10, 3), 3)
        self.assertIsNone(days_of_cover(10, 0))
        self.assertEqual(suggest_order_qty(10, 2.5, 7, 3, lot_size=12), 24)
        self.assertEqual(suggest_order_qty(100, 2, 7), 0)
        with self.assertRaises(ValueError):
            daily_demand([(1, 1)], 0)

    def test_demand_from_orders(self):
        _, stock, service = make()
        service.place([("B200", 1)], now=2)
        gone = service.place([("B200", 1)], now=2)
        service.place([("B200", 1)], now=4)
        service.cancel(gone.id)
        self.assertEqual(demand_from_orders(service.orders(), "B200"), [(2, 1), (4, 1)])

    def test_adjustments(self):
        _, stock, _ = make()
        audit = AuditLog()
        changes = apply_count(stock, {"L4": 3, "L1": 10, "L2": 22}, audit)
        self.assertEqual([(c.lot_id, c.delta) for c in changes], [("L2", 2), ("L4", -1)])
        self.assertEqual(shrinkage(changes), 1)
        self.assertEqual([e.data["delta"] for e in audit.events("stock_adjusted")], [2, -1])
        with self.assertRaises(WarehouseError):
            apply_count(stock, {"L4": 1, "NOPE": 1})
        with self.assertRaises(WarehouseError):
            apply_count(stock, {"L4": -1})
        self.assertEqual(stock.lot("L4").qty, 3)

    def test_write_off(self):
        _, stock, _ = make()
        changes = write_off_expired(stock, 20)
        self.assertEqual([(c.lot_id, c.before, c.reason) for c in changes], [("L2", 20, "expired"), ("L5", 6, "expired"), ("L6", 6, "expired")])
        self.assertEqual(stock.lot("L1").qty, 10)
        self.assertEqual(write_off_expired(stock, 20), [])
        self.assertEqual(shrinkage(changes), 32)

    def test_audit_log(self):
        audit = AuditLog()
        audit.log("a", x=1)
        audit.log("b")
        audit.log("a", x=2)
        self.assertEqual([e.seq for e in audit.events("a")], [1, 3])
        self.assertEqual(audit.last("a").data, {"x": 2})
        self.assertIsNone(audit.last("zzz"))
        self.assertEqual(len(audit), 3)


if __name__ == "__main__":
    unittest.main()
