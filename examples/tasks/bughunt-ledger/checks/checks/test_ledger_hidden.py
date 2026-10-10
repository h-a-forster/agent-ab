import unittest
from datetime import date

from ledgerlib import (AccountError, Chart, CurrencyMismatch, ImportFailure, Journal, Ledger, LedgerError,
                       Money, RateTable, UnbalancedEntry, account_statement, balance_sheet, import_csv,
                       income_statement, month_range, parse_amount, parse_date, quarter_range, trial_balance,
                       year_range)
from ledgerlib import periods
from ledgerlib.reports import format_tree

D = date


def make_chart():
    c = Chart()
    c.add("1000", "Assets", "asset")
    c.add("1100", "Cash", "asset", parent="1000")
    c.add("1200", "Receivables", "asset", parent="1000")
    c.add("1210", "Trade", "asset", parent="1200")
    c.add("2000", "Liabilities", "liability")
    c.add("2100", "Loans", "liability", parent="2000")
    c.add("3000", "Equity", "equity")
    c.add("4000", "Income", "income")
    c.add("4100", "Sales", "income", parent="4000")
    c.add("5000", "Expenses", "expense")
    c.add("5100", "Rent", "expense", parent="5000")
    c.add("1500", "Euro bank", "asset", currency="EUR")
    return c


def make_ledger():
    led = Ledger(make_chart())
    led.rates.set_rate("EUR", "USD", "1")
    return led


class AllocateSymptoms(unittest.TestCase):
    def test_negative_three_way(self):
        self.assertEqual(Money(-100).allocate([1, 1, 1]), [Money(-34), Money(-33), Money(-33)])

    def test_negative_split(self):
        self.assertEqual(Money(-100).split(3), [Money(-34), Money(-33), Money(-33)])
        self.assertEqual(Money(-1).split(2), [Money(-1), Money(0)])
        self.assertEqual(Money(-10, "EUR").split(4), [Money(-3, "EUR"), Money(-3, "EUR"), Money(-2, "EUR"), Money(-2, "EUR")])

    def test_negative_weighted(self):
        self.assertEqual(Money(-101).allocate([3, 1]), [Money(-76), Money(-25)])

    def test_mirror_property(self):
        for cents in (1, 2, 7, 99, 100, 1001):
            for ratios in ([1, 1], [1, 2, 3], [5, 0, 5, 1]):
                pos = Money(cents).allocate(ratios)
                neg = Money(-cents).allocate(ratios)
                self.assertEqual(neg, [-p for p in pos], (cents, ratios))
                self.assertEqual(sum(p.cents for p in neg), -cents)

    def test_positive_unchanged(self):
        self.assertEqual(Money(100).allocate([1, 1, 1]), [Money(34), Money(33), Money(33)])
        self.assertEqual(Money(101).allocate([3, 1]), [Money(76), Money(25)])
        self.assertEqual(Money(0).allocate([1, 2]), [Money(0), Money(0)])


class FxSymptoms(unittest.TestCase):
    def rates(self):
        r = RateTable("USD")
        r.set_rate("EUR", "USD", "0.5")
        r.set_rate("GBP", "USD", "1.5")
        return r

    def test_half_rounds_up(self):
        r = self.rates()
        self.assertEqual(r.convert(Money(25, "EUR"), "USD"), Money(13))
        self.assertEqual(r.convert(Money(5, "EUR"), "USD"), Money(3))
        self.assertEqual(r.convert(Money(1, "EUR"), "USD"), Money(1))

    def test_negative_half_rounds_away(self):
        r = self.rates()
        self.assertEqual(r.convert(Money(-25, "EUR"), "USD"), Money(-13))
        self.assertEqual(r.convert(Money(-1, "EUR"), "USD"), Money(-1))

    def test_inverse_rate(self):
        r = RateTable("USD")
        r.set_rate("EUR", "USD", "2")
        self.assertEqual(r.convert(Money(25), "EUR"), Money(13, "EUR"))
        self.assertEqual(r.convert(Money(27), "EUR"), Money(14, "EUR"))

    def test_triangulated(self):
        r = self.rates()
        # EUR -> GBP = 0.5 * (1/1.5) = 1/3 ; 10 * 1/3 = 3.33 -> 3 ; 15 -> 5
        self.assertEqual(r.convert(Money(10, "EUR"), "GBP"), Money(3, "GBP"))
        self.assertEqual(r.convert(Money(15, "EUR"), "GBP"), Money(5, "GBP"))
        # GBP -> EUR = 3 ; exact
        self.assertEqual(r.convert(Money(5, "GBP"), "EUR"), Money(15, "EUR"))

    def test_fine_rate_half(self):
        r = RateTable("USD")
        r.set_rate("JPY", "USD", "0.005")
        self.assertEqual(r.convert(Money(100, "JPY"), "USD"), Money(1))
        self.assertEqual(r.convert(Money(300, "JPY"), "USD"), Money(2))
        self.assertEqual(r.convert(Money(500, "JPY"), "USD"), Money(3))

    def test_ledger_balance_in(self):
        led = make_ledger()
        led.rates.set_rate("EUR", "USD", "0.5")
        led.post(D(2024, 1, 2), "fund", [("1500", Money(25, "EUR")), ("1500", Money(-25, "EUR"))])
        led.post(D(2024, 1, 3), "more", [("1500", Money(25, "EUR")), ("1500", Money(-25, "EUR"))])
        led.chart.add("3500", "EUR equity", "equity", currency="EUR")
        led.post(D(2024, 1, 4), "inject", [("1500", Money(25, "EUR")), ("3500", Money(-25, "EUR"))])
        self.assertEqual(led.balance_in("1500", "USD"), Money(13))
        self.assertEqual(led.balance_in("3500", "USD"), Money(-13))

    def test_trial_balance_converts(self):
        led = make_ledger()
        led.chart.add("3500", "EUR equity", "equity", currency="EUR")
        led.rates.set_rate("EUR", "USD", "0.5")
        led.post(D(2024, 1, 4), "inject", [("1500", Money(25, "EUR")), ("3500", Money(-25, "EUR"))])
        rows = trial_balance(led)
        self.assertEqual(rows[0], ("1500", "Euro bank", Money(13), Money(0)))
        self.assertEqual(rows[1], ("3500", "EUR equity", Money(0), Money(13)))
        self.assertEqual(rows[-1], ("", "Total", Money(13), Money(13)))

    def test_income_statement_converts(self):
        led = make_ledger()
        led.chart.add("4500", "EUR sales", "income", currency="EUR")
        led.rates.set_rate("EUR", "USD", "0.5")
        led.post(D(2024, 1, 4), "sale", [("1500", Money(25, "EUR")), ("4500", Money(-25, "EUR"))])
        out = income_statement(led, D(2024, 1, 1), D(2024, 1, 31))
        self.assertEqual(out["income"], Money(13))
        self.assertEqual(out["net"], Money(13))


class DescendantSymptoms(unittest.TestCase):
    def test_descendants_exclude_self(self):
        c = make_chart()
        self.assertEqual(c.descendants("1000"), ["1100", "1200", "1210"])
        self.assertEqual(c.descendants("1200"), ["1210"])
        self.assertEqual(c.descendants("1100"), [])
        self.assertEqual(c.descendants("5000"), ["5100"])

    def test_rollup_with_own_postings(self):
        led = make_ledger()
        led.post(D(2024, 1, 5), "a", [("1000", Money(700)), ("3000", Money(-700))])
        led.post(D(2024, 1, 6), "b", [("1100", Money(300)), ("3000", Money(-300))])
        led.post(D(2024, 1, 7), "c", [("1210", Money(50)), ("3000", Money(-50))])
        self.assertEqual(led.balance("1000", rollup=True), Money(1050))
        self.assertEqual(led.balance("1000"), Money(700))
        self.assertEqual(led.balance("1200", rollup=True), Money(50))
        self.assertEqual(led.balance("3000", rollup=True), Money(-1050))
        self.assertEqual(led.natural_balance("3000"), Money(1050))

    def test_rollup_as_of(self):
        led = make_ledger()
        led.post(D(2024, 1, 5), "a", [("4000", Money(-200)), ("1100", Money(200))])
        led.post(D(2024, 2, 5), "b", [("4100", Money(-100)), ("1100", Money(100))])
        self.assertEqual(led.natural_balance("4000", rollup=True), Money(300))
        self.assertEqual(led.natural_balance("4000", as_of=D(2024, 1, 31), rollup=True), Money(200))

    def test_balance_sheet_and_tree(self):
        led = make_ledger()
        led.post(D(2024, 1, 5), "a", [("1000", Money(700)), ("3000", Money(-700))])
        led.post(D(2024, 1, 6), "b", [("1100", Money(300)), ("3000", Money(-300))])
        sheet = balance_sheet(led)
        self.assertEqual(sheet["assets"], Money(1000))
        self.assertEqual(sheet["equity"], Money(1000))
        self.assertEqual(sheet["liabilities"], Money(0))

    def test_walk_lists_each_account_once(self):
        c = make_chart()
        walked = list(c.walk())
        codes = [code for code, _ in walked]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(sorted(codes), c.codes())
        self.assertEqual(walked[:4], [("1000", 0), ("1100", 1), ("1200", 1), ("1210", 2)])

    def test_format_tree(self):
        led = make_ledger()
        led.post(D(2024, 1, 6), "b", [("1100", Money(300)), ("3000", Money(-300))])
        lines = format_tree(led).split("\n")
        self.assertEqual(lines[0], "1000 Assets  3.00 USD")
        self.assertEqual(lines[1], "  1100 Cash  3.00 USD")
        self.assertEqual(len(lines), len(led.chart))


class LeapSymptoms(unittest.TestCase):
    def test_is_leap(self):
        for y, expected in ((2000, True), (1900, False), (2100, False), (2024, True), (2023, False), (2400, True), (1600, True)):
            self.assertEqual(periods.is_leap(y), expected, y)

    def test_month_range_feb_2000(self):
        self.assertEqual(month_range(2000, 2), (D(2000, 2, 1), D(2000, 2, 29)))
        self.assertEqual(month_range(1900, 2)[1], D(1900, 2, 28))
        self.assertEqual(periods.days_in_month(2000, 2), 29)
        self.assertEqual(periods.days_in_month(2100, 2), 28)

    def test_fiscal_year_ending_in_leap_feb(self):
        self.assertEqual(periods.fiscal_year_range(1999, 3), (D(1999, 3, 1), D(2000, 2, 29)))
        self.assertEqual(periods.fiscal_year_range(2023, 3), (D(2023, 3, 1), D(2024, 2, 29)))
        self.assertEqual(periods.fiscal_year_range(2099, 3), (D(2099, 3, 1), D(2100, 2, 28)))

    def test_quarter_with_feb(self):
        self.assertEqual(quarter_range(2000, 1), (D(2000, 1, 1), D(2000, 3, 31)))
        self.assertEqual(quarter_range(2000, 2), (D(2000, 4, 1), D(2000, 6, 30)))

    def test_parse_date_leap_day_2000(self):
        self.assertEqual(parse_date("2000-02-29"), D(2000, 2, 29))
        self.assertEqual(parse_date("02/29/2000"), D(2000, 2, 29))
        self.assertEqual(parse_date("2400-02-29"), D(2400, 2, 29))

    def test_parse_date_rejects_non_leap(self):
        for text in ("1900-02-29", "2100-02-29", "2023-02-29", "2001-02-29"):
            with self.assertRaises(ImportFailure, msg=text):
                parse_date(text)

    def test_import_csv_leap_row(self):
        led = make_ledger()
        posted = import_csv("2000-02-29,Leap sale,10.00,4000\n", led, "1100")
        self.assertEqual(posted[0].date, D(2000, 2, 29))

    def test_income_statement_for_leap_month(self):
        led = make_ledger()
        led.post(D(2000, 2, 29), "late", [("1100", Money(900)), ("4100", Money(-900))])
        led.post(D(2000, 2, 10), "early", [("1100", Money(100)), ("4100", Money(-100))])
        start, end = month_range(2000, 2)
        self.assertEqual(income_statement(led, start, end)["income"], Money(1000))


class TagSymptoms(unittest.TestCase):
    def test_default_tags_not_shared(self):
        j = Journal()
        a = j.post(D(2024, 1, 1), "a", [("x", Money(1)), ("y", Money(-1))])
        b = j.post(D(2024, 1, 2), "b", [("x", Money(1)), ("y", Money(-1))])
        a.add_tag("audit")
        self.assertEqual(a.tags, ["audit"])
        self.assertEqual(b.tags, [])
        self.assertEqual(j.tagged("audit"), [a])

    def test_through_ledger_post(self):
        led = make_ledger()
        a = led.post(D(2024, 1, 1), "a", [("1100", Money(1)), ("4000", Money(-1))])
        b = led.post(D(2024, 1, 2), "b", [("1100", Money(1)), ("4000", Money(-1))])
        b.add_tag("reviewed")
        self.assertEqual(a.tags, [])
        self.assertEqual(led.journal.tagged("reviewed"), [b])

    def test_caller_list_is_copied(self):
        j = Journal()
        mine = ["q1"]
        e = j.post(D(2024, 1, 1), "a", [("x", Money(1)), ("y", Money(-1))], tags=mine)
        mine.append("later")
        e.add_tag("own")
        self.assertEqual(e.tags, ["q1", "own"])
        self.assertEqual(mine, ["q1", "later"])

    def test_reversal_tags_are_independent(self):
        j = Journal()
        e = j.post(D(2024, 1, 1), "a", [("x", Money(1)), ("y", Money(-1))], tags=["t"])
        r = j.reverse(e.id)
        r.add_tag("undo")
        self.assertEqual(e.tags, ["t"])
        self.assertEqual(r.tags, ["t", "undo"])

    def test_reversal_of_untagged_entry(self):
        j = Journal()
        e = j.post(D(2024, 1, 1), "a", [("x", Money(1)), ("y", Money(-1))])
        r = j.reverse(e.id)
        r.add_tag("undo")
        self.assertEqual(e.tags, [])
        other = j.post(D(2024, 1, 3), "c", [("x", Money(1)), ("y", Money(-1))])
        self.assertEqual(other.tags, [])


class AmountSymptoms(unittest.TestCase):
    def test_small_negative(self):
        self.assertEqual(parse_amount("-0.05"), -5)
        self.assertEqual(parse_amount("-0.5"), -50)
        self.assertEqual(parse_amount("-0.99"), -99)
        self.assertEqual(parse_amount("-0"), 0)

    def test_signs_and_symbols(self):
        self.assertEqual(parse_amount("-$0.99"), -99)
        self.assertEqual(parse_amount("($0.05)"), -5)
        self.assertEqual(parse_amount("(0.05)"), -5)
        self.assertEqual(parse_amount("-1,234.50"), -123450)
        self.assertEqual(parse_amount("-5"), -500)
        self.assertEqual(parse_amount("-12.34"), -1234)

    def test_import_row_negative_cents(self):
        led = make_ledger()
        posted = import_csv("2024-01-02,Fee,-0.05,5100\n2024-01-03,Fee2,-$0.50,5100\n", led, "1100")
        self.assertEqual(posted[0].lines[0].amount, Money(-5))
        self.assertEqual(posted[0].lines[1].amount, Money(5))
        self.assertEqual(posted[1].lines[0].amount, Money(-50))
        self.assertEqual(led.balance("1100"), Money(-55))
        self.assertEqual(led.balance("5100"), Money(55))

    def test_positive_still_fine(self):
        self.assertEqual(parse_amount("0.05"), 5)
        self.assertEqual(parse_amount("0.5"), 50)
        self.assertEqual(parse_amount(".5"), 50)
        self.assertEqual(parse_amount("1,000"), 100000)


class CacheSymptoms(unittest.TestCase):
    def setUp(self):
        self.led = make_ledger()
        self.e1 = self.led.post(D(2024, 1, 5), "sale", [("1100", Money(5000)), ("4100", Money(-5000))])
        self.e2 = self.led.post(D(2024, 1, 9), "sale2", [("1100", Money(700)), ("4100", Money(-700))])

    def test_reverse_refreshes_balance(self):
        self.assertEqual(self.led.balance("1100"), Money(5700))
        self.led.reverse(self.e1.id)
        self.assertEqual(self.led.balance("1100"), Money(700))
        self.assertEqual(self.led.balance("4100"), Money(-700))

    def test_reverse_refreshes_rollup_and_natural(self):
        self.assertEqual(self.led.balance("1000", rollup=True), Money(5700))
        self.assertEqual(self.led.natural_balance("4000", rollup=True), Money(5700))
        self.led.reverse(self.e1.id)
        self.assertEqual(self.led.balance("1000", rollup=True), Money(700))
        self.assertEqual(self.led.natural_balance("4000", rollup=True), Money(700))

    def test_reverse_refreshes_as_of(self):
        d = D(2024, 1, 31)
        self.assertEqual(self.led.balance("1100", as_of=d), Money(5700))
        self.led.reverse(self.e2.id, date=D(2024, 1, 20))
        self.assertEqual(self.led.balance("1100", as_of=d), Money(5000))
        self.assertEqual(self.led.balance("1100", as_of=D(2024, 1, 15)), Money(5700))

    def test_reverse_many(self):
        self.assertEqual(self.led.balance("1100"), Money(5700))
        self.led.reverse_many([self.e1.id, self.e2.id])
        self.assertEqual(self.led.balance("1100"), Money(0))

    def test_reports_after_reverse(self):
        self.assertEqual(self.led.balance_in("1100", "USD"), Money(5700))
        self.assertEqual(balance_sheet(self.led)["assets"], Money(5700))
        self.led.reverse(self.e1.id)
        self.assertEqual(self.led.balance_in("1100", "USD"), Money(700))
        self.assertEqual(balance_sheet(self.led)["assets"], Money(700))
        self.assertEqual(trial_balance(self.led)[0][:3], ("1100", "Cash", Money(700)))

    def test_post_still_refreshes(self):
        self.assertEqual(self.led.balance("1100"), Money(5700))
        self.led.post(D(2024, 1, 11), "x", [("1100", Money(1)), ("4100", Money(-1))])
        self.assertEqual(self.led.balance("1100"), Money(5701))


class MoneyRegression(unittest.TestCase):
    def test_basic_ops(self):
        self.assertEqual(Money(5) + Money(6), Money(11))
        self.assertEqual(abs(Money(-5)), Money(5))
        self.assertEqual(3 * Money(4), Money(12))
        self.assertTrue(Money(1) < Money(2))
        self.assertTrue(Money(2) >= Money(2))
        self.assertTrue(Money(-1).is_negative())
        self.assertTrue(Money.zero().is_zero())
        self.assertFalse(Money(0))

    def test_hash_and_eq(self):
        self.assertEqual(len({Money(1), Money(1), Money(1, "EUR")}), 2)
        self.assertNotEqual(Money(1), Money(1, "EUR"))
        self.assertNotEqual(Money(1), 1)

    def test_immutable(self):
        m = Money(5)
        with self.assertRaises(AttributeError):
            m.cents = 6

    def test_type_checks(self):
        with self.assertRaises(TypeError):
            Money(1.5)
        with self.assertRaises(TypeError):
            Money(True)
        with self.assertRaises(TypeError):
            Money(1) * 1.5
        with self.assertRaises(TypeError):
            Money(1) + 1

    def test_mismatch(self):
        for op in (lambda a, b: a + b, lambda a, b: a - b, lambda a, b: a < b):
            with self.assertRaises(CurrencyMismatch):
                op(Money(1), Money(1, "EUR"))

    def test_format(self):
        self.assertEqual(Money(5).format(), "0.05 USD")
        self.assertEqual(Money(100000000).format(), "1,000,000.00 USD")
        self.assertEqual(Money(-123456).format("$"), "-$1,234.56")
        self.assertEqual(Money(0).format("$"), "$0.00")

    def test_allocate_misc(self):
        self.assertEqual(Money(10).allocate([1]), [Money(10)])
        self.assertEqual(Money(5).allocate([1, 1, 1, 1, 1, 1, 1]), [Money(1)] * 5 + [Money(0)] * 2)
        self.assertEqual(Money(10, "EUR").allocate([2, 3]), [Money(4, "EUR"), Money(6, "EUR")])
        for bad in ([-1, 2], [0], [0, 0]):
            with self.assertRaises(ValueError):
                Money(5).allocate(bad)
        for bad in (0, -1, 1.5, True):
            with self.assertRaises(ValueError):
                Money(5).split(bad)

    def test_total(self):
        from ledgerlib.money import total
        self.assertEqual(total([Money(1), Money(2)]), Money(3))
        self.assertEqual(total([], "EUR"), Money(0, "EUR"))


class FxRegression(unittest.TestCase):
    def test_same_currency(self):
        r = RateTable("USD")
        m = Money(7, "EUR")
        self.assertIs(r.convert(m, "EUR"), m)

    def test_exact_conversions(self):
        r = RateTable("USD")
        r.set_rate("EUR", "USD", "1.10")
        self.assertEqual(r.convert(Money(1000, "EUR"), "USD"), Money(1100))
        self.assertEqual(r.convert(Money(-1000, "EUR"), "USD"), Money(-1100))
        self.assertEqual(r.convert(Money(1100), "EUR"), Money(1000, "EUR"))
        self.assertEqual(r.convert(Money(0, "EUR"), "USD"), Money(0))

    def test_errors(self):
        r = RateTable("USD")
        with self.assertRaises(ValueError):
            r.set_rate("EUR", "USD", "0")
        with self.assertRaises(LedgerError):
            r.rate("EUR", "GBP")
        r.set_rate("EUR", "USD", 1.1)
        with self.assertRaises(LedgerError):
            r.rate("EUR", "GBP")

    def test_currencies(self):
        r = RateTable("USD")
        r.set_rate("EUR", "USD", 1)
        r.set_rate("GBP", "USD", 1)
        self.assertEqual(r.currencies(), ["EUR", "GBP", "USD"])

    def test_non_half_rounding(self):
        r = RateTable("USD")
        r.set_rate("EUR", "USD", "1.1")
        self.assertEqual(r.convert(Money(1, "EUR"), "USD"), Money(1))
        self.assertEqual(r.convert(Money(4, "EUR"), "USD"), Money(4))
        self.assertEqual(r.convert(Money(7, "EUR"), "USD"), Money(8))


class ChartRegression(unittest.TestCase):
    def test_structure(self):
        c = make_chart()
        self.assertEqual(c.roots(), ["1000", "1500", "2000", "3000", "4000", "5000"])
        self.assertEqual(c.children("1000"), ["1100", "1200"])
        self.assertEqual(c.ancestors("1210"), ["1200", "1000"])
        self.assertEqual(c.depth("1210"), 2)
        self.assertEqual(c.path("1210"), "Assets:Receivables:Trade")
        self.assertTrue(c.is_leaf("1100"))
        self.assertFalse(c.is_leaf("1000"))
        self.assertEqual(c.of_type("income"), ["4000", "4100"])
        self.assertIn("1100", c)
        self.assertEqual(len(c), 12)

    def test_currency_inheritance(self):
        c = Chart()
        c.add("1", "Eur", "asset", currency="EUR")
        c.add("11", "Sub", "asset", parent="1")
        self.assertEqual(c.get("11").currency, "EUR")
        with self.assertRaises(AccountError):
            c.add("12", "Bad", "asset", parent="1", currency="USD")

    def test_errors(self):
        c = make_chart()
        for call in (lambda: c.add("1100", "d", "asset"), lambda: c.add("9", "d", "bogus"),
                     lambda: c.add("9", "d", "asset", parent="nope"), lambda: c.get("nope"),
                     lambda: c.children("nope"), lambda: c.descendants("nope"),
                     lambda: c.add("9", "d", "income", parent="1000")):
            with self.assertRaises(AccountError):
                call()

    def test_debit_normal(self):
        c = make_chart()
        self.assertTrue(c.get("1100").debit_normal)
        self.assertTrue(c.get("5100").debit_normal)
        self.assertFalse(c.get("2100").debit_normal)
        self.assertFalse(c.get("4100").debit_normal)

    def test_descendants_order_deep(self):
        c = Chart()
        c.add("a", "A", "asset")
        c.add("b", "B", "asset", parent="a")
        c.add("c", "C", "asset", parent="a")
        c.add("d", "D", "asset", parent="b")
        c.add("e", "E", "asset", parent="b")
        self.assertEqual(c.descendants("a"), ["b", "d", "e", "c"])


class JournalRegression(unittest.TestCase):
    def test_unbalanced_variants(self):
        j = Journal()
        with self.assertRaises(UnbalancedEntry):
            j.post(D(2024, 1, 1), "m", [("a", Money(1))])
        with self.assertRaises(UnbalancedEntry):
            j.post(D(2024, 1, 1), "m", [("a", Money(1)), ("b", Money(-2))])
        with self.assertRaises(UnbalancedEntry):
            j.post(D(2024, 1, 1), "m", [("a", Money(1)), ("b", Money(-1, "EUR"))])
        self.assertEqual(len(j), 0)

    def test_multi_currency_balanced(self):
        j = Journal()
        j.post(D(2024, 1, 1), "m", [("a", Money(1)), ("b", Money(-1)), ("c", Money(2, "EUR")), ("d", Money(-2, "EUR"))])
        self.assertEqual(len(j), 1)

    def test_queries(self):
        j = Journal()
        e1 = j.post(D(2024, 1, 1), "one", [("a", Money(1)), ("b", Money(-1))], tags=["x"])
        e2 = j.post(D(2024, 1, 5), "two", [("b", Money(1)), ("c", Money(-1))])
        e3 = j.post(D(2024, 1, 9), "three", [("a", Money(1)), ("c", Money(-1))], tags=["x", "y"])
        self.assertEqual(j.between(D(2024, 1, 1), D(2024, 1, 5)), [e1, e2])
        self.assertEqual(j.between(D(2024, 1, 2), D(2024, 1, 8)), [e2])
        self.assertEqual(j.between(D(2024, 1, 9), D(2024, 1, 9)), [e3])
        self.assertEqual(j.up_to(D(2024, 1, 5)), [e1, e2])
        self.assertEqual(j.up_to(None), [e1, e2, e3])
        self.assertEqual(j.for_account("c"), [e2, e3])
        self.assertEqual(j.tagged("x"), [e1, e3])
        self.assertEqual(j.tagged("y"), [e3])
        self.assertEqual(e3.accounts(), ["a", "c"])
        self.assertEqual(j.get(2), e2)
        with self.assertRaises(LedgerError):
            j.get(99)

    def test_ids_increment(self):
        j = Journal()
        ids = [j.post(D(2024, 1, 1), "m", [("a", Money(1)), ("b", Money(-1))]).id for _ in range(3)]
        self.assertEqual(ids, [1, 2, 3])

    def test_tag_methods(self):
        j = Journal()
        e = j.post(D(2024, 1, 1), "m", [("a", Money(1)), ("b", Money(-1))], tags=["a"])
        e.add_tag("a")
        e.add_tag("b")
        self.assertEqual(e.tags, ["a", "b"])
        self.assertTrue(e.has_tag("b"))
        self.assertFalse(e.has_tag("zzz"))

    def test_reverse_details(self):
        j = Journal()
        e = j.post(D(2024, 1, 1), "rent", [("a", Money(5)), ("b", Money(-5))])
        r = j.reverse(e.id, date=D(2024, 2, 1))
        self.assertEqual(r.memo, "Reversal of #1: rent")
        self.assertEqual(r.date, D(2024, 2, 1))
        self.assertEqual(r.reverses, 1)
        self.assertEqual(e.reversed_by, r.id)
        with self.assertRaises(LedgerError):
            j.reverse(r.id)
        r2 = j.reverse(j.post(D(2024, 1, 3), "z", [("a", Money(1)), ("b", Money(-1))]).id)
        self.assertEqual(r2.date, D(2024, 1, 3))

    def test_line_types(self):
        from ledgerlib import Line
        with self.assertRaises(TypeError):
            Line("a", 5)
        self.assertEqual(Line("a", Money(1)), Line("a", Money(1)))


class LedgerRegression(unittest.TestCase):
    def test_currency_mismatch_on_post(self):
        led = make_ledger()
        with self.assertRaises(CurrencyMismatch):
            led.post(D(2024, 1, 1), "x", [("1100", Money(1, "EUR")), ("1500", Money(-1, "EUR"))])
        self.assertEqual(len(led.journal), 0)

    def test_unknown_account(self):
        led = make_ledger()
        with self.assertRaises(AccountError):
            led.post(D(2024, 1, 1), "x", [("1100", Money(1)), ("nope", Money(-1))])

    def test_balance_as_of_boundary(self):
        led = make_ledger()
        led.post(D(2024, 1, 5), "a", [("1100", Money(10)), ("4100", Money(-10))])
        self.assertEqual(led.balance("1100", as_of=D(2024, 1, 5)), Money(10))
        self.assertEqual(led.balance("1100", as_of=D(2024, 1, 4)), Money(0))

    def test_natural_signs(self):
        led = make_ledger()
        led.post(D(2024, 1, 5), "loan", [("1100", Money(1000)), ("2100", Money(-1000))])
        self.assertEqual(led.natural_balance("2100"), Money(1000))
        self.assertEqual(led.natural_balance("1100"), Money(1000))
        self.assertEqual(led.balance("2100"), Money(-1000))

    def test_history_and_repeat_queries(self):
        led = make_ledger()
        e = led.post(D(2024, 1, 5), "a", [("1100", Money(10)), ("4100", Money(-10))])
        self.assertEqual(led.history("1100"), [(e, Money(10))])
        self.assertEqual(led.balance("1100"), led.balance("1100"))
        led.post(D(2024, 1, 6), "b", [("1100", Money(5)), ("4100", Money(-5))])
        self.assertEqual(led.balance("1100"), Money(15))

    def test_empty_balance_currency(self):
        led = make_ledger()
        self.assertEqual(led.balance("1500"), Money(0, "EUR"))

    def test_unknown_balance(self):
        with self.assertRaises(AccountError):
            make_ledger().balance("zzz")

    def test_balance_in_same_currency(self):
        led = make_ledger()
        led.post(D(2024, 1, 5), "a", [("1100", Money(10)), ("4100", Money(-10))])
        self.assertEqual(led.balance_in("1100", "USD"), Money(10))


class ReportRegression(unittest.TestCase):
    def setUp(self):
        self.led = make_ledger()
        self.led.post(D(2024, 1, 5), "sale", [("1100", Money(5000)), ("4100", Money(-5000))])
        self.led.post(D(2024, 1, 9), "rent", [("5100", Money(1200)), ("1100", Money(-1200))])
        self.led.post(D(2024, 2, 1), "sale2", [("1210", Money(800)), ("4100", Money(-800))])

    def test_trial_balance(self):
        rows = trial_balance(self.led)
        self.assertEqual([r[0] for r in rows], ["1100", "1210", "4100", "5100", ""])
        self.assertEqual(rows[2], ("4100", "Sales", Money(0), Money(5800)))
        self.assertEqual(rows[-1], ("", "Total", Money(5800), Money(5800)))

    def test_trial_balance_as_of(self):
        rows = trial_balance(self.led, as_of=D(2024, 1, 31))
        self.assertEqual([r[0] for r in rows], ["1100", "4100", "5100", ""])
        self.assertEqual(rows[-1][2:], (Money(5000), Money(5000)))

    def test_income_statement_periods(self):
        jan = income_statement(self.led, D(2024, 1, 1), D(2024, 1, 31))
        self.assertEqual((jan["income"], jan["expenses"], jan["net"]), (Money(5000), Money(1200), Money(3800)))
        feb = income_statement(self.led, *month_range(2024, 2))
        self.assertEqual((feb["income"], feb["expenses"], feb["net"]), (Money(800), Money(0), Money(800)))
        edge = income_statement(self.led, D(2024, 1, 9), D(2024, 2, 1))
        self.assertEqual(edge["net"], Money(-1200 + 800))

    def test_balance_sheet(self):
        sheet = balance_sheet(self.led)
        self.assertEqual(sheet["assets"], Money(4600))
        self.assertEqual(sheet["liabilities"], Money(0))

    def test_account_statement(self):
        rows = account_statement(self.led, "1100", D(2024, 1, 6), D(2024, 1, 31))
        self.assertEqual(rows[0], (D(2024, 1, 6), "Opening balance", Money(0), Money(5000)))
        self.assertEqual(rows[1], (D(2024, 1, 9), "rent", Money(-1200), Money(3800)))
        self.assertEqual(len(rows), 2)
        full = account_statement(self.led, "1100", D(2024, 1, 1), D(2024, 12, 31))
        self.assertEqual([r[3] for r in full], [Money(0), Money(5000), Money(3800)])


class ImportRegression(unittest.TestCase):
    def test_parse_amount_forms(self):
        cases = {"12": 1200, "12.3": 1230, "12.34": 1234, "$5": 500, "1,234.56": 123456, "(12.50)": -1250,
                 "  7.00 ": 700, "-7.25": -725, "0": 0, "$1,000,000.00": 100000000}
        for text, cents in cases.items():
            self.assertEqual(parse_amount(text), cents, text)

    def test_parse_amount_errors(self):
        for text in ("", "  ", "abc", "1.234", "1.2.3", "$", "-", "12a"):
            with self.assertRaises(ImportFailure, msg=text):
                parse_amount(text)

    def test_parse_date_forms(self):
        self.assertEqual(parse_date("2024-12-31"), D(2024, 12, 31))
        self.assertEqual(parse_date(" 1/2/2024 "), D(2024, 1, 2))
        for text in ("2024-13-01", "2024-00-10", "2024-04-31", "2024-01-00", "nope", "2024/01/01x", "1/2"):
            with self.assertRaises(ImportFailure, msg=text):
                parse_date(text)

    def test_import_csv(self):
        led = make_ledger()
        text = "Date,Memo,Amount,Account\n\n2024-01-05,Sale,50.00,4100\n2024-01-09,\"Rent, Jan\",(12.00),5100\n"
        posted = import_csv(text, led, "1100")
        self.assertEqual([p.memo for p in posted], ["Sale", "Rent, Jan"])
        self.assertEqual(led.balance("1100"), Money(3800))
        self.assertEqual(led.balance("4100"), Money(-5000))

    def test_import_errors_report_line(self):
        led = make_ledger()
        with self.assertRaises(ImportFailure) as cm:
            import_csv("2024-01-05,a,1.00,4100\n2024-01-06,b,xx,4100\n", led, "1100")
        self.assertEqual(cm.exception.line, 2)
        with self.assertRaises(ImportFailure) as cm:
            import_csv("2024-01-05,a,1.00\n", led, "1100")
        self.assertEqual(cm.exception.line, 1)
        with self.assertRaises(ImportFailure) as cm:
            import_csv("date,memo,amount,account\n13/40/2024,a,1.00,4100\n", led, "1100")
        self.assertEqual(cm.exception.line, 2)

    def test_currency_argument(self):
        led = make_ledger()
        posted = import_csv("2024-01-05,a,1.00,3500\n", Ledger(_eur_chart()), "1500", currency="EUR")
        self.assertEqual(posted[0].lines[0].amount, Money(100, "EUR"))


def _eur_chart():
    c = Chart()
    c.add("1500", "Euro bank", "asset", currency="EUR")
    c.add("3500", "Eq", "equity", currency="EUR")
    return c


class PeriodRegression(unittest.TestCase):
    def test_month_ranges(self):
        self.assertEqual(month_range(2024, 1), (D(2024, 1, 1), D(2024, 1, 31)))
        self.assertEqual(month_range(2024, 4)[1], D(2024, 4, 30))
        self.assertEqual(month_range(2024, 12)[1], D(2024, 12, 31))
        self.assertEqual(month_range(2023, 2)[1], D(2023, 2, 28))
        self.assertEqual(month_range(2024, 2)[1], D(2024, 2, 29))
        with self.assertRaises(ValueError):
            month_range(2024, 13)

    def test_quarters_and_years(self):
        self.assertEqual(quarter_range(2024, 1), (D(2024, 1, 1), D(2024, 3, 31)))
        self.assertEqual(quarter_range(2024, 3), (D(2024, 7, 1), D(2024, 9, 30)))
        self.assertEqual(year_range(2024), (D(2024, 1, 1), D(2024, 12, 31)))
        with self.assertRaises(ValueError):
            quarter_range(2024, 5)

    def test_fiscal(self):
        self.assertEqual(periods.fiscal_year_range(2024, 1), (D(2024, 1, 1), D(2024, 12, 31)))
        self.assertEqual(periods.fiscal_year_range(2024, 7), (D(2024, 7, 1), D(2025, 6, 30)))
        self.assertEqual(periods.fiscal_year_range(2024, 12), (D(2024, 12, 1), D(2025, 11, 30)))

    def test_iter_months(self):
        self.assertEqual(list(periods.iter_months(D(2023, 11, 15), D(2024, 2, 1))),
                         [(2023, 11), (2023, 12), (2024, 1), (2024, 2)])
        self.assertEqual(list(periods.iter_months(D(2024, 5, 1), D(2024, 5, 31))), [(2024, 5)])

    def test_misc(self):
        self.assertEqual(periods.previous_day(D(2024, 3, 1)), D(2024, 2, 29))
        self.assertEqual(periods.month_label(2024, 3), "Mar 2024")
        self.assertEqual(periods.days_in_month(2024, 2), 29)
        self.assertEqual(periods.days_in_month(2024, 9), 30)
        self.assertTrue(periods.is_leap(2024))
        self.assertFalse(periods.is_leap(2023))


if __name__ == "__main__":
    unittest.main()
