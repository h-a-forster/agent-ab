import unittest
from datetime import datetime

from cronx import CronError, CronExpr, matches, next_after, upcoming


class ParseTests(unittest.TestCase):
    def test_fields(self):
        e = CronExpr.parse("0,30 9-11 * 1 1-5")
        self.assertEqual(e.minutes, {0, 30})
        self.assertEqual(e.hours, {9, 10, 11})
        self.assertEqual(len(e.days), 31)
        self.assertEqual(e.months, {1})
        self.assertEqual(e.weekdays, {1, 2, 3, 4, 5})

    def test_errors(self):
        for bad in ["* * * *", "60 * * * *", "* 24 * * *", "5-3 * * * *", "a * * * *", "* * 0 * *", "1,,2 * * * *"]:
            with self.assertRaises(CronError, msg=bad):
                CronExpr.parse(bad)


class ScheduleTests(unittest.TestCase):
    def test_matches(self):
        e = CronExpr.parse("30 2 * * *")
        self.assertTrue(matches(e, datetime(2024, 3, 1, 2, 30, 45)))
        self.assertFalse(matches(e, datetime(2024, 3, 1, 2, 31)))

    def test_next_after(self):
        e = CronExpr.parse("30 2 * * 1-5")
        self.assertEqual(next_after(e, datetime(2024, 3, 1, 12, 0)), datetime(2024, 3, 4, 2, 30))
        self.assertEqual(next_after(e, datetime(2024, 3, 4, 2, 0, 59)), datetime(2024, 3, 4, 2, 30))
        self.assertEqual(next_after(e, datetime(2024, 3, 4, 2, 30)), datetime(2024, 3, 5, 2, 30))

    def test_upcoming(self):
        e = CronExpr.parse("0 12 1 * *")
        got = upcoming(e, datetime(2024, 1, 15), 3)
        self.assertEqual(got, [datetime(2024, 2, 1, 12), datetime(2024, 3, 1, 12), datetime(2024, 4, 1, 12)])


if __name__ == "__main__":
    unittest.main()
