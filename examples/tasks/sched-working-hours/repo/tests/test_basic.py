import unittest
from datetime import datetime, time

from bizhours import WorkCalendar, add_working_minutes, working_minutes_between


class Basics(unittest.TestCase):
    def setUp(self):
        self.cal = WorkCalendar()

    def test_is_working(self):
        self.assertTrue(self.cal.is_working(datetime(2024, 1, 1, 9, 0)))
        self.assertFalse(self.cal.is_working(datetime(2024, 1, 1, 17, 0)))
        self.assertFalse(self.cal.is_working(datetime(2024, 1, 6, 10, 0)))

    def test_next_open(self):
        self.assertEqual(self.cal.next_open(datetime(2024, 1, 5, 18)), datetime(2024, 1, 8, 9))
        self.assertEqual(self.cal.next_open(datetime(2024, 1, 1, 7)), datetime(2024, 1, 1, 9))

    def test_add(self):
        self.assertEqual(add_working_minutes(self.cal, datetime(2024, 1, 5, 16), 120), datetime(2024, 1, 8, 10))
        self.assertEqual(add_working_minutes(self.cal, datetime(2024, 1, 1, 9), 60), datetime(2024, 1, 1, 10))

    def test_between(self):
        self.assertEqual(working_minutes_between(self.cal, datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 10)), 60)
        self.assertEqual(working_minutes_between(self.cal, datetime(2024, 1, 5, 16), datetime(2024, 1, 8, 10)), 120)

    def test_custom_hours(self):
        cal = WorkCalendar(time(8), time(12), workdays=(5,))
        self.assertTrue(cal.is_working(datetime(2024, 1, 6, 8)))
        self.assertFalse(cal.is_working(datetime(2024, 1, 1, 8)))

    def test_bad_window(self):
        with self.assertRaises(ValueError):
            WorkCalendar(time(9), time(9))


if __name__ == "__main__":
    unittest.main()
