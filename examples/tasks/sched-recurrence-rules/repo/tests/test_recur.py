import unittest
from datetime import date

from recur import Rule, between, format_rule, occurrences, parse_rule


class Daily(unittest.TestCase):
    def test_count(self):
        got = list(occurrences(parse_rule("FREQ=DAILY;INTERVAL=3;COUNT=4"), date(2024, 1, 1)))
        self.assertEqual(got, [date(2024, 1, 1), date(2024, 1, 4), date(2024, 1, 7), date(2024, 1, 10)])

    def test_until_inclusive(self):
        rule = parse_rule("FREQ=DAILY;UNTIL=2024-01-03")
        self.assertEqual(len(list(occurrences(rule, date(2024, 1, 1)))), 3)

    def test_weekly_same_weekday(self):
        rule = parse_rule("FREQ=WEEKLY;INTERVAL=2;COUNT=3")
        self.assertEqual(
            list(occurrences(rule, date(2024, 1, 3))),
            [date(2024, 1, 3), date(2024, 1, 17), date(2024, 1, 31)],
        )

    def test_between_is_lazy_on_unbounded_rules(self):
        rule = parse_rule("FREQ=DAILY")
        self.assertEqual(between(rule, date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)),
                         [date(2024, 1, 2), date(2024, 1, 3)])


class Text(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(format_rule(parse_rule("freq=weekly;count=2;interval=2")), "FREQ=WEEKLY;INTERVAL=2;COUNT=2")

    def test_errors(self):
        for bad in ("", "COUNT=3", "FREQ=DAILY;FREQ=DAILY", "FREQ=DAILY;COUNT=0", "FREQ=DAILY;COUNT=1;UNTIL=2024-01-01"):
            with self.assertRaises(ValueError):
                parse_rule(bad)

    def test_rule_validation(self):
        with self.assertRaises(ValueError):
            Rule("HOURLY")


if __name__ == "__main__":
    unittest.main()
