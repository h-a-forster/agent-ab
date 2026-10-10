import unittest
from datetime import date, datetime, time, timezone

from bizhours import WorkCalendar, add_working_minutes, working_minutes_between

DT = datetime
LUNCH = {wd: [(time(9), time(12)), (time(13), time(17))] for wd in range(5)}


def lunch_cal(**kw):
    return WorkCalendar(windows=LUNCH, **kw)


class Windows(unittest.TestCase):
    def test_is_working_with_lunch(self):
        cal = lunch_cal()
        self.assertTrue(cal.is_working(DT(2024, 1, 1, 11, 59)))
        self.assertFalse(cal.is_working(DT(2024, 1, 1, 12, 0)))
        self.assertFalse(cal.is_working(DT(2024, 1, 1, 12, 30)))
        self.assertTrue(cal.is_working(DT(2024, 1, 1, 13, 0)))
        self.assertFalse(cal.is_working(DT(2024, 1, 1, 17, 0)))
        self.assertFalse(cal.is_working(DT(2024, 1, 6, 10, 0)))

    def test_next_open_around_lunch(self):
        cal = lunch_cal()
        self.assertEqual(cal.next_open(DT(2024, 1, 1, 12, 0)), DT(2024, 1, 1, 13))
        self.assertEqual(cal.next_open(DT(2024, 1, 1, 10, 15)), DT(2024, 1, 1, 10, 15))
        self.assertEqual(cal.next_open(DT(2024, 1, 1, 17, 0)), DT(2024, 1, 2, 9))
        self.assertEqual(cal.next_open(DT(2024, 1, 5, 17, 30)), DT(2024, 1, 8, 9))

    def test_different_hours_per_day(self):
        cal = WorkCalendar(windows={0: [(time(9), time(17))], 4: [(time(9), time(13))], 5: []})
        self.assertEqual(cal.next_open(DT(2024, 1, 2, 10)), DT(2024, 1, 5, 9))
        self.assertFalse(cal.is_working(DT(2024, 1, 5, 13)))
        self.assertFalse(cal.is_working(DT(2024, 1, 6, 10)))
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 5, 12), 120), DT(2024, 1, 8, 10))

    def test_unordered_and_touching_windows(self):
        cal = WorkCalendar(windows={0: [(time(13), time(17)), (time(9), time(13))]})
        self.assertTrue(cal.is_working(DT(2024, 1, 1, 13)))
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 1, 9), 480), DT(2024, 1, 1, 17))
        self.assertEqual(working_minutes_between(cal, DT(2024, 1, 1, 8), DT(2024, 1, 2)), 480)

    def test_invalid_windows(self):
        bad = [
            {0: [(time(9), time(12)), (time(11), time(15))]},
            {0: [(time(9), time(9))]},
            {0: [(time(10), time(9))]},
            {7: [(time(9), time(17))]},
            {-1: [(time(9), time(17))]},
            {},
            {0: [], 3: []},
        ]
        for windows in bad:
            with self.subTest(windows=windows):
                with self.assertRaises(ValueError):
                    WorkCalendar(windows=windows)

    def test_legacy_form_still_works(self):
        cal = WorkCalendar(time(8), time(12), workdays=(5,))
        self.assertTrue(cal.is_working(DT(2024, 1, 6, 8)))
        cal2 = WorkCalendar(open=time(10), close=time(11))
        self.assertEqual(add_working_minutes(cal2, DT(2024, 1, 1, 10), 90), DT(2024, 1, 2, 10, 30))
        with self.assertRaises(ValueError):
            WorkCalendar(time(9), time(9))


class Holidays(unittest.TestCase):
    def test_holiday_not_working(self):
        cal = WorkCalendar(holidays=[date(2024, 1, 2)])
        self.assertFalse(cal.is_working(DT(2024, 1, 2, 10)))
        self.assertEqual(cal.next_open(DT(2024, 1, 1, 17)), DT(2024, 1, 3, 9))

    def test_add_over_holiday_and_weekend(self):
        cal = WorkCalendar(holidays=[date(2024, 1, 8)])
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 5, 16), 120), DT(2024, 1, 9, 10))

    def test_consecutive_holidays(self):
        cal = WorkCalendar(holidays=[date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)])
        self.assertEqual(cal.next_open(DT(2024, 1, 1, 17)), DT(2024, 1, 5, 9))

    def test_between_skips_holidays(self):
        cal = lunch_cal(holidays=[date(2024, 1, 2)])
        self.assertEqual(working_minutes_between(cal, DT(2024, 1, 1), DT(2024, 1, 4)), 2 * 420)

    def test_observe_weekends(self):
        # 2024-01-06 Saturday -> Friday 2024-01-05 ; 2024-01-14 Sunday -> Monday 2024-01-15
        cal = WorkCalendar(holidays=[date(2024, 1, 6), date(2024, 1, 14)], observe_weekends=True)
        self.assertFalse(cal.is_working(DT(2024, 1, 5, 10)))
        self.assertTrue(cal.is_working(DT(2024, 1, 4, 10)))
        self.assertFalse(cal.is_working(DT(2024, 1, 15, 10)))
        self.assertTrue(cal.is_working(DT(2024, 1, 12, 10)))
        self.assertEqual(cal.next_open(DT(2024, 1, 4, 17)), DT(2024, 1, 8, 9))

    def test_weekend_holiday_ignored_when_not_observing(self):
        cal = WorkCalendar(holidays=[date(2024, 1, 6)])
        self.assertTrue(cal.is_working(DT(2024, 1, 5, 10)))

    def test_observe_weekday_holiday_unchanged(self):
        cal = WorkCalendar(holidays=[date(2024, 1, 3)], observe_weekends=True)
        self.assertFalse(cal.is_working(DT(2024, 1, 3, 10)))
        self.assertTrue(cal.is_working(DT(2024, 1, 2, 10)))


class Add(unittest.TestCase):
    def test_zero_returns_start(self):
        cal = lunch_cal()
        for start in (DT(2024, 1, 6, 3, 4, 5), DT(2024, 1, 1, 12, 30), DT(2024, 1, 1, 10)):
            self.assertEqual(add_working_minutes(cal, start, 0), start)

    def test_across_lunch(self):
        self.assertEqual(add_working_minutes(lunch_cal(), DT(2024, 1, 1, 11), 90), DT(2024, 1, 1, 13, 30))

    def test_ends_exactly_at_window_close(self):
        cal = lunch_cal()
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 1, 11), 60), DT(2024, 1, 1, 12))
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 1, 9), 420), DT(2024, 1, 1, 17))

    def test_start_in_break_or_weekend(self):
        cal = lunch_cal()
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 1, 12, 15), 30), DT(2024, 1, 1, 13, 30))
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 6, 10), 30), DT(2024, 1, 8, 9, 30))
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 1, 20), 15), DT(2024, 1, 2, 9, 15))

    def test_multi_day(self):
        cal = lunch_cal()
        # 1000 minutes = 2 days (840) + 160 -> Wed 09:00 + 160
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 1, 9), 1000), DT(2024, 1, 3, 11, 40))

    def test_fractional_minutes_and_seconds(self):
        cal = WorkCalendar()
        self.assertEqual(add_working_minutes(cal, DT(2024, 1, 1, 9, 0, 30), 1.5), DT(2024, 1, 1, 9, 2))

    def test_invalid_minutes(self):
        for bad in (-1, -0.5):
            with self.assertRaises(ValueError):
                add_working_minutes(WorkCalendar(), DT(2024, 1, 1, 9), bad)

    def test_large_amount_is_fast(self):
        cal = lunch_cal(holidays=[date(2024, 12, 25)])
        end = add_working_minutes(cal, DT(2024, 1, 1, 9), 420 * 1000)
        # 1000 working days after, minus nothing: verify with the inverse
        self.assertEqual(working_minutes_between(cal, DT(2024, 1, 1, 9), end), 420 * 1000)
        self.assertEqual(end.hour, 17)

    def test_aware_datetime_rejected(self):
        with self.assertRaises(ValueError):
            add_working_minutes(WorkCalendar(), DT(2024, 1, 1, 9, tzinfo=timezone.utc), 5)


class Between(unittest.TestCase):
    def test_lunch_excluded(self):
        self.assertEqual(working_minutes_between(lunch_cal(), DT(2024, 1, 1, 8), DT(2024, 1, 1, 18)), 420)
        self.assertEqual(working_minutes_between(lunch_cal(), DT(2024, 1, 1, 11), DT(2024, 1, 1, 14)), 120)

    def test_weekend_and_multi_day(self):
        self.assertEqual(working_minutes_between(lunch_cal(), DT(2024, 1, 5, 16), DT(2024, 1, 8, 10)), 120)
        self.assertEqual(working_minutes_between(lunch_cal(), DT(2024, 1, 1), DT(2024, 1, 15)), 10 * 420)

    def test_negative_and_zero(self):
        cal = lunch_cal()
        a, b = DT(2024, 1, 1, 8), DT(2024, 1, 3, 12)
        self.assertEqual(working_minutes_between(cal, b, a), -working_minutes_between(cal, a, b))
        self.assertEqual(working_minutes_between(cal, a, a), 0)

    def test_seconds_fractional(self):
        v = working_minutes_between(WorkCalendar(), DT(2024, 1, 1, 9, 0, 0), DT(2024, 1, 1, 9, 0, 30))
        self.assertAlmostEqual(v, 0.5)
        self.assertIsInstance(v, float)

    def test_half_open_end(self):
        self.assertEqual(working_minutes_between(WorkCalendar(), DT(2024, 1, 1, 16), DT(2024, 1, 1, 17)), 60)
        self.assertEqual(working_minutes_between(WorkCalendar(), DT(2024, 1, 1, 17), DT(2024, 1, 2, 9)), 0)

    def test_aware_rejected(self):
        with self.assertRaises(ValueError):
            working_minutes_between(WorkCalendar(), DT(2024, 1, 1), DT(2024, 1, 2, tzinfo=timezone.utc))

    def test_add_between_inverse(self):
        cal = lunch_cal(holidays=[date(2024, 1, 3)])
        for start in (DT(2024, 1, 1, 7), DT(2024, 1, 1, 12, 20), DT(2024, 1, 5, 16, 59)):
            for m in (1, 59, 421, 2000):
                end = add_working_minutes(cal, start, m)
                self.assertEqual(working_minutes_between(cal, start, end), m)


if __name__ == "__main__":
    unittest.main()
