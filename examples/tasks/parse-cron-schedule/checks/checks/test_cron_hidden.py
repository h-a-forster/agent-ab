import unittest
from datetime import datetime, timedelta, timezone

from cronx import CronError, CronExpr, matches, next_after, upcoming


def P(text):
    return CronExpr.parse(text)


def D(*a):
    return datetime(*a)


class Steps(unittest.TestCase):
    def test_star_steps(self):
        self.assertEqual(P("*/15 * * * *").minutes, {0, 15, 30, 45})
        self.assertEqual(P("*/7 * * * *").minutes, set(range(0, 60, 7)))
        self.assertEqual(P("* */5 * * *").hours, {0, 5, 10, 15, 20})
        self.assertEqual(P("* * */10 * *").days, {1, 11, 21, 31})
        self.assertEqual(P("* * * */3 *").months, {1, 4, 7, 10})

    def test_range_and_single_steps(self):
        self.assertEqual(P("10-30/10 * * * *").minutes, {10, 20, 30})
        self.assertEqual(P("5/20 * * * *").minutes, {5, 25, 45})
        self.assertEqual(P("0-59/30 * * * *").minutes, {0, 30})
        self.assertEqual(P("* 22/1 * * *").hours, {22, 23})
        self.assertEqual(P("*/70 * * * *").minutes, {0})
        self.assertEqual(P("3-4/5 * * * *").minutes, {3})

    def test_lists_mixed(self):
        self.assertEqual(P("1,5-7,*/30 * * * *").minutes, {0, 1, 5, 6, 7, 30})
        self.assertEqual(P("0 1,2-3/2,10 * * *").hours, {1, 2, 10})

    def test_unchanged_basics(self):
        e = P("  0,30   9-11 * 1 1-5 ")
        self.assertEqual((e.minutes, e.hours, e.months, e.weekdays), ({0, 30}, {9, 10, 11}, {1}, {1, 2, 3, 4, 5}))
        self.assertEqual(len(e.days), 31)


class Names(unittest.TestCase):
    def test_month_names(self):
        self.assertEqual(P("* * * JAN-MAR *").months, {1, 2, 3})
        self.assertEqual(P("* * * jan,Mar,DEC *").months, {1, 3, 12})
        self.assertEqual(P("* * * JAN-DEC/4 *").months, {1, 5, 9})
        self.assertEqual(P("* * * 2,SEP *").months, {2, 9})

    def test_dow_names(self):
        self.assertEqual(P("* * * * MON-FRI").weekdays, {1, 2, 3, 4, 5})
        self.assertEqual(P("* * * * sun").weekdays, {0})
        self.assertEqual(P("* * * * Sat").weekdays, {6})
        self.assertEqual(P("* * * * mon-fri/2").weekdays, {1, 3, 5})
        self.assertEqual(P("* * * * SAT,SUN").weekdays, {6, 0})
        self.assertEqual(P("* * * * 1-WED").weekdays, {1, 2, 3})

    def test_seven_is_sunday(self):
        self.assertEqual(P("* * * * 7").weekdays, {0})
        self.assertEqual(P("* * * * 5-7").weekdays, {5, 6, 0})
        self.assertEqual(P("* * * * 0-7").weekdays, set(range(7)))
        self.assertEqual(P("* * * * 1-7/2").weekdays, {1, 3, 5, 0})
        self.assertEqual(P("* * * * */2").weekdays, {0, 2, 4, 6})
        self.assertEqual(P("* * * * *").weekdays, set(range(7)))
        self.assertEqual(P("* * * * 0,7").weekdays, {0})

    def test_question_mark(self):
        self.assertEqual(P("0 0 ? * 1").days, set(range(1, 32)))
        self.assertEqual(P("0 0 1 * ?").weekdays, set(range(7)))
        P("0 0 ? * ?")

    def test_macros(self):
        e = P("@yearly")
        self.assertEqual((e.minutes, e.hours, e.days, e.months), ({0}, {0}, {1}, {1}))
        self.assertEqual(P("@annually").months, {1})
        e = P("@monthly")
        self.assertEqual((e.days, len(e.months)), ({1}, 12))
        self.assertEqual(P("@weekly").weekdays, {0})
        self.assertEqual(P("@weekly").days, set(range(1, 32)))
        self.assertEqual((P("@daily").minutes, P("@Midnight").hours), ({0}, {0}))
        self.assertEqual(P("@HOURLY").minutes, {0})
        self.assertEqual(len(P("@hourly").hours), 24)
        self.assertEqual(P("  @daily  ").hours, {0})


class Errors(unittest.TestCase):
    def test_bad_expressions(self):
        bad = [
            "", "   ", "* * * *", "* * * * * *", "@reboot", "@daily extra", "@", "@dailyy",
            "60 * * * *", "* 24 * * *", "* * 0 * *", "* * 32 * *", "* * * 0 *", "* * * 13 *", "* * * * 8",
            "5-3 * * * *", "* 10-9 * * *", "* * * * 6-1", "* * * * FRI-SUN", "* * * MAR-JAN *",
            "*/0 * * * *", "*/-1 * * * *", "*/ * * * *", "*/x * * * *", "5-10/0 * * * *", "1-5/2/3 * * * *",
            "1- * * * *", "-5 * * * *", "1--5 * * * *", "a-b * * * *", "+5 * * * *", "５ * * * *",
            "1,,2 * * * *", ",1 * * * *", "1, * * * *", "* * * mon *", "* * * * jan", "jan * * * *",
            "* mon * * *", "* * mon * *", "* * * * MON-", "? * * * *", "* ? * * *", "* * * ? *",
            "?/2 * * * *", "1,? * * * *", "* * * * ??", "*/2/3 * * * *", "1.5 * * * *",
            "* * * * MONDAY", "* * * foo *", "-1 * * * *", "*-5 * * * *", "* * * * 0-8",
        ]
        for text in bad:
            with self.assertRaises(CronError, msg=repr(text)):
                CronExpr.parse(text)

    def test_cron_error_is_value_error(self):
        self.assertTrue(issubclass(CronError, ValueError))


class DayRules(unittest.TestCase):
    def test_or_when_both_restricted(self):
        e = P("0 0 13 * 5")  # 13th OR Friday
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2024, 3, 8))
        self.assertEqual(next_after(e, D(2024, 3, 8)), D(2024, 3, 13))
        self.assertEqual(next_after(e, D(2024, 3, 13)), D(2024, 3, 15))
        self.assertTrue(matches(e, D(2024, 3, 13)))
        self.assertTrue(matches(e, D(2024, 3, 8)))
        self.assertFalse(matches(e, D(2024, 3, 9)))

    def test_and_when_one_is_star(self):
        e = P("0 0 13 * *")
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2024, 3, 13))
        self.assertFalse(matches(e, D(2024, 3, 8)))
        e = P("0 0 * * 5")
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2024, 3, 8))

    def test_star_with_step_still_counts_as_star(self):
        e = P("0 0 */2 * 1")  # odd days AND Monday
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2024, 3, 11))
        self.assertTrue(matches(e, D(2024, 3, 11)))
        self.assertFalse(matches(e, D(2024, 3, 4)))
        self.assertFalse(matches(e, D(2024, 3, 3)))
        e = P("0 0 5 * */2")  # dow starts with '*' -> dom 5 AND dow in {0,2,4,6}
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2024, 3, 5))

    def test_question_mark_behaves_like_star(self):
        self.assertEqual(next_after(P("0 0 ? * 1"), D(2024, 3, 1)), D(2024, 3, 4))
        self.assertEqual(next_after(P("30 8 1 * ?"), D(2024, 3, 1, 9)), D(2024, 4, 1, 8, 30))

    def test_month_restricts_both_cases(self):
        e = P("0 0 13 6 5")
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2024, 6, 7))
        self.assertEqual(next_after(e, D(2024, 6, 28)), D(2025, 6, 6))

    def test_sunday_zero_and_seven(self):
        sunday = D(2024, 3, 3, 12, 0)
        for dow in ("0", "7", "SUN", "sun", "6-7", "0,7"):
            self.assertTrue(matches(P("0 12 * * " + dow), sunday), dow)
        self.assertFalse(matches(P("0 12 * * 1-5"), sunday))
        self.assertTrue(matches(P("0 12 * * MON-FRI"), D(2024, 3, 4, 12, 0)))
        self.assertEqual(next_after(P("0 0 * * 7"), D(2024, 3, 1)), D(2024, 3, 3))

    def test_short_months(self):
        e = P("0 0 31 * *")
        self.assertEqual(next_after(e, D(2024, 4, 15)), D(2024, 5, 31))
        self.assertEqual(next_after(e, D(2024, 5, 31)), D(2024, 7, 31))
        self.assertEqual(next_after(e, D(2024, 1, 31)), D(2024, 3, 31))
        e = P("0 0 30 * *")
        self.assertEqual(next_after(e, D(2024, 1, 30)), D(2024, 3, 30))

    def test_leap_day(self):
        e = P("0 0 29 2 *")
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2028, 2, 29))
        self.assertEqual(next_after(e, D(2024, 2, 29)), D(2028, 2, 29))
        self.assertEqual(next_after(e, D(2024, 2, 28, 23, 59)), D(2024, 2, 29))
        self.assertEqual(next_after(e, D(2096, 3, 1)), D(2104, 2, 29))
        self.assertEqual(next_after(e, D(1899, 1, 1)), D(1904, 2, 29))


class NextAfter(unittest.TestCase):
    def test_strictly_after(self):
        e = P("30 2 * * *")
        self.assertEqual(next_after(e, D(2024, 3, 1, 2, 30)), D(2024, 3, 2, 2, 30))
        self.assertEqual(next_after(e, D(2024, 3, 1, 2, 29, 59, 999999)), D(2024, 3, 1, 2, 30))

    def test_seconds_ignored(self):
        e = P("1 10 * * *")
        self.assertEqual(next_after(e, D(2024, 3, 1, 10, 0, 30)), D(2024, 3, 1, 10, 1))
        e = P("0 10 * * *")
        self.assertEqual(next_after(e, D(2024, 3, 1, 10, 0, 30)), D(2024, 3, 2, 10, 0))
        self.assertEqual(next_after(e, D(2024, 3, 1, 9, 59, 59)), D(2024, 3, 1, 10, 0))
        self.assertEqual(next_after(P("* * * * *"), D(2024, 3, 1, 10, 0, 59)), D(2024, 3, 1, 10, 1))

    def test_rollovers(self):
        self.assertEqual(next_after(P("59 23 31 12 *"), D(2024, 12, 31, 23, 59)), D(2025, 12, 31, 23, 59))
        self.assertEqual(next_after(P("0 0 1 1 *"), D(2024, 12, 31, 23, 59)), D(2025, 1, 1))
        self.assertEqual(next_after(P("*/20 * * * *"), D(2024, 3, 1, 23, 45)), D(2024, 3, 2, 0, 0))
        self.assertEqual(next_after(P("15 3 * * *"), D(2024, 2, 28, 4)), D(2024, 2, 29, 3, 15))
        self.assertEqual(next_after(P("0 0 * * *"), D(2023, 2, 28, 0, 0, 1)), D(2023, 3, 1))

    def test_hours_and_minutes_combination(self):
        e = P("10,40 8-9 * * *")
        self.assertEqual(next_after(e, D(2024, 3, 1, 8, 10)), D(2024, 3, 1, 8, 40))
        self.assertEqual(next_after(e, D(2024, 3, 1, 8, 40)), D(2024, 3, 1, 9, 10))
        self.assertEqual(next_after(e, D(2024, 3, 1, 9, 40)), D(2024, 3, 2, 8, 10))
        self.assertEqual(next_after(e, D(2024, 3, 1, 7, 55)), D(2024, 3, 1, 8, 10))

    def test_named_schedule(self):
        e = P("0 9 * JAN,JUL MON-FRI")
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2024, 7, 1, 9))
        self.assertEqual(next_after(e, D(2024, 7, 5, 9)), D(2024, 7, 8, 9))

    def test_macros_schedule(self):
        self.assertEqual(next_after(P("@weekly"), D(2024, 3, 1)), D(2024, 3, 3))
        self.assertEqual(next_after(P("@monthly"), D(2024, 3, 1)), D(2024, 4, 1))
        self.assertEqual(next_after(P("@yearly"), D(2024, 3, 1)), D(2025, 1, 1))
        self.assertEqual(next_after(P("@hourly"), D(2024, 3, 1, 5, 30)), D(2024, 3, 1, 6))
        self.assertEqual(next_after(P("@daily"), D(2024, 3, 1, 5, 30)), D(2024, 3, 2))

    def test_tzinfo_preserved(self):
        tz = timezone(timedelta(hours=5))
        got = next_after(P("0 0 * * *"), datetime(2024, 3, 1, 12, tzinfo=tz))
        self.assertEqual(got, datetime(2024, 3, 2, tzinfo=tz))
        self.assertIs(got.tzinfo, tz)
        self.assertIsNone(next_after(P("0 0 * * *"), D(2024, 3, 1)).tzinfo)

    def test_never_matches(self):
        for text in ("0 0 30 2 *", "0 0 31 4 *", "0 0 31 2,4,6,9,11 *"):
            with self.assertRaises(CronError, msg=text):
                next_after(P(text), D(2024, 3, 1))

    def test_ten_year_window(self):
        e = P("0 0 1 1 *")
        self.assertEqual(next_after(e, D(2024, 3, 1)), D(2025, 1, 1))
        # next hit of Feb 29 from 2097-03-01 is 2104 (2100 is not a leap year): within 10 years.
        self.assertEqual(next_after(P("0 0 29 2 *"), D(2097, 3, 1)), D(2104, 2, 29))


class Upcoming(unittest.TestCase):
    def test_sequence(self):
        got = upcoming(P("*/20 9 * * 1-5"), D(2024, 3, 1, 9, 30), 5)
        self.assertEqual(got, [D(2024, 3, 1, 9, 40), D(2024, 3, 4, 9, 0), D(2024, 3, 4, 9, 20),
                               D(2024, 3, 4, 9, 40), D(2024, 3, 5, 9, 0)])

    def test_counts(self):
        e = P("* * * * *")
        self.assertEqual(upcoming(e, D(2024, 3, 1), 0), [])
        self.assertEqual(len(upcoming(e, D(2024, 3, 1), 3000)), 3000)
        with self.assertRaises(ValueError):
            upcoming(e, D(2024, 3, 1), -1)

    def test_strictly_increasing_and_matching(self):
        e = P("7,37 */6 */9 JAN-JUN MON,WED,FRI")
        times = upcoming(e, D(2024, 1, 1), 60)
        self.assertEqual(times, sorted(set(times)))
        for t in times:
            self.assertTrue(matches(e, t), t)

    def test_every_match_found_brute_force(self):
        e = P("5,45 3,15 10-20 2,3 2-4")
        start = D(2024, 2, 1)
        want = []
        t = start
        end = D(2025, 4, 1)
        while t < end:
            t += timedelta(minutes=1)
            if matches(e, t):
                want.append(t)
        got = []
        t = start
        while True:
            t = next_after(e, t)
            if t >= end:
                break
            got.append(t)
        self.assertEqual(got, want)

    def test_brute_force_star_dom(self):
        e = P("0 */8 */11 * 0")
        start = D(2024, 1, 1)
        end = D(2024, 12, 31)
        want = [t for t in (start + timedelta(hours=h) for h in range(0, 24 * 365)) if matches(e, t)]
        got = []
        t = start - timedelta(minutes=1)
        while True:
            t = next_after(e, t)
            if t >= end:
                break
            got.append(t)
        self.assertEqual(got, [w for w in want if w < end])


class Matches(unittest.TestCase):
    def test_ignores_seconds(self):
        e = P("30 2 * * *")
        self.assertTrue(matches(e, D(2024, 3, 1, 2, 30, 59, 999)))

    def test_steps_and_names(self):
        e = P("*/15 8-17 * MAR MON-FRI")
        self.assertTrue(matches(e, D(2024, 3, 1, 9, 45)))
        self.assertFalse(matches(e, D(2024, 3, 2, 9, 45)))
        self.assertFalse(matches(e, D(2024, 4, 1, 9, 45)))
        self.assertFalse(matches(e, D(2024, 3, 1, 9, 40)))

    def test_aware_datetime(self):
        e = P("0 0 * * *")
        self.assertTrue(matches(e, datetime(2024, 3, 1, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
