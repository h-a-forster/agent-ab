import unittest
from datetime import date

from ledgerlib import (AccountError, Chart, CurrencyMismatch, ImportFailure, Journal, Ledger, LedgerError,
                       Money, RateTable, UnbalancedEntry, account_statement, balance_sheet, import_csv,
                       income_statement, month_range, parse_amount, parse_date, quarter_range, trial_balance)


def make_ledger():
    chart = Chart()
    chart.add("1000", "Assets", "asset")
    chart.add("1100", "Cash", "asset", parent="1000")
    chart.add("2000", "Liabilities", "liability")
    chart.add("3000", "Equity", "equity")
    chart.add("4000", "Income", "income")
    chart.add("5000", "Expenses", "expense")
    return Ledger(chart)


class MoneyTests(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(Money(150) + Money(250), Money(400))
        self.assertEqual(Money(150) - Money(250), Money(-100))
        self.assertEqual(-Money(5), Money(-5))
        self.assertEqual(Money(7) * 3, Money(21))

    def test_currency_mismatch(self):
        with self.assertRaises(CurrencyMismatch):
            Money(1, "USD") + Money(1, "EUR")

    def test_format(self):
        self.assertEqual(str(Money(123456)), "1,234.56 USD")
        self.assertEqual(Money(-5, "EUR").format(), "-0.05 EUR")

    def test_allocate_positive(self):
        self.assertEqual(Money(100).allocate([1, 1, 1]), [Money(34), Money(33), Money(33)])
        self.assertEqual(Money(100).split(4), [Money(25)] * 4)

    def test_allocate_errors(self):
        with self.assertRaises(ValueError):
            Money(10).allocate([])
        with self.assertRaises(ValueError):
            Money(10).allocate([0, 0])


class FxTests(unittest.TestCase):
    def test_convert_exact(self):
        rates = RateTable("USD")
        rates.set_rate("EUR", "USD", "1.25")
        self.assertEqual(rates.convert(Money(1000, "EUR"), "USD"), Money(1250, "USD"))
        self.assertEqual(rates.convert(Money(1250, "USD"), "EUR"), Money(1000, "EUR"))

    def test_missing_rate(self):
        with self.assertRaises(LedgerError):
            RateTable("USD").convert(Money(1, "EUR"), "USD")


class ChartTests(unittest.TestCase):
    def test_tree(self):
        led = make_ledger()
        self.assertEqual(led.chart.children("1000"), ["1100"])
        self.assertEqual(led.chart.ancestors("1100"), ["1000"])
        self.assertEqual(led.chart.path("1100"), "Assets:Cash")

    def test_errors(self):
        led = make_ledger()
        with self.assertRaises(AccountError):
            led.chart.add("1100", "Dup", "asset")
        with self.assertRaises(AccountError):
            led.chart.add("1200", "Bad", "expense", parent="1000")


class JournalTests(unittest.TestCase):
    def test_unbalanced(self):
        led = make_ledger()
        with self.assertRaises(UnbalancedEntry):
            led.post(date(2024, 1, 1), "x", [("1100", Money(5)), ("4000", Money(-4))])

    def test_between_inclusive(self):
        j = Journal()
        for d in (1, 2, 3):
            j.post(date(2024, 3, d), "m", [("a", Money(1)), ("b", Money(-1))])
        self.assertEqual([e.date.day for e in j.between(date(2024, 3, 2), date(2024, 3, 3))], [2, 3])

    def test_reverse_lines(self):
        j = Journal()
        e = j.post(date(2024, 3, 1), "m", [("a", Money(5)), ("b", Money(-5))])
        r = j.reverse(e.id)
        self.assertEqual([l.amount for l in r.lines], [Money(-5), Money(5)])
        self.assertEqual(e.reversed_by, r.id)
        with self.assertRaises(LedgerError):
            j.reverse(e.id)


class LedgerTests(unittest.TestCase):
    def test_balances(self):
        led = make_ledger()
        led.post(date(2024, 1, 5), "sale", [("1100", Money(5000)), ("4000", Money(-5000))])
        led.post(date(2024, 1, 9), "rent", [("5000", Money(1200)), ("1100", Money(-1200))])
        self.assertEqual(led.balance("1100"), Money(3800))
        self.assertEqual(led.balance("1100", as_of=date(2024, 1, 6)), Money(5000))
        self.assertEqual(led.natural_balance("4000"), Money(5000))
        self.assertEqual(led.balance("1000", rollup=True), Money(3800))

    def test_currency_check(self):
        led = make_ledger()
        with self.assertRaises(CurrencyMismatch):
            led.post(date(2024, 1, 5), "x", [("1100", Money(5, "EUR")), ("4000", Money(-5, "EUR"))])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.led = make_ledger()
        self.led.post(date(2024, 1, 5), "sale", [("1100", Money(5000)), ("4000", Money(-5000))])
        self.led.post(date(2024, 1, 9), "rent", [("5000", Money(1200)), ("1100", Money(-1200))])

    def test_trial_balance(self):
        rows = trial_balance(self.led)
        self.assertEqual(rows[-1], ("", "Total", Money(5000), Money(5000)))
        self.assertEqual(rows[0][:2], ("1100", "Cash"))

    def test_income_statement(self):
        out = income_statement(self.led, date(2024, 1, 1), date(2024, 1, 31))
        self.assertEqual((out["income"], out["expenses"], out["net"]), (Money(5000), Money(1200), Money(3800)))

    def test_balance_sheet(self):
        self.assertEqual(balance_sheet(self.led)["assets"], Money(3800))

    def test_account_statement(self):
        rows = account_statement(self.led, "1100", date(2024, 1, 6), date(2024, 1, 31))
        self.assertEqual(rows[0][3], Money(5000))
        self.assertEqual(rows[-1][3], Money(3800))


class ImportTests(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(parse_amount("12.5"), 1250)
        self.assertEqual(parse_amount("$1,234.56"), 123456)
        self.assertEqual(parse_amount("(12.50)"), -1250)
        self.assertEqual(parse_amount("-7.25"), -725)

    def test_parse_date(self):
        self.assertEqual(parse_date("2024-02-29"), date(2024, 2, 29))
        self.assertEqual(parse_date("03/04/2024"), date(2024, 3, 4))
        with self.assertRaises(ImportFailure):
            parse_date("2023-02-29")

    def test_import_csv(self):
        led = make_ledger()
        text = "date,memo,amount,account\n2024-01-05,Sale,50.00,4000\n2024-01-09,\"Rent, Jan\",-12.00,5000\n"
        posted = import_csv(text, led, "1100")
        self.assertEqual(len(posted), 2)
        self.assertEqual(posted[1].memo, "Rent, Jan")
        self.assertEqual(led.balance("1100"), Money(3800))


class PeriodTests(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(month_range(2024, 2), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(month_range(2023, 2)[1], date(2023, 2, 28))
        self.assertEqual(quarter_range(2024, 4), (date(2024, 10, 1), date(2024, 12, 31)))


if __name__ == "__main__":
    unittest.main()
