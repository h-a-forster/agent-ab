import itertools
import unittest
from datetime import date

from recur import Rule, between, format_rule, occurrences, parse_rule

D = date


def occ(text, start, n=None):
    it = occurrences(parse_rule(text), start)
    return list(it if n is None else itertools.islice(it, n))


class ParseNew(unittest.TestCase):
    def test_byday_sorted_unique_case_insensitive(self):
        self.assertEqual(parse_rule("FREQ=WEEKLY;BYDAY=we,MO,Mo").byday, (0, 2))

    def test_byday_errors(self):
        for bad in ("FREQ=WEEKLY;BYDAY=XX", "FREQ=DAILY;BYDAY=MO", "FREQ=MONTHLY;BYDAY=MO",
                    "FREQ=WEEKLY;BYDAY=MO,", "FREQ=WEEKLY;BYDAY="):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_rule(bad)

    def test_rule_constructor_validates_byday(self):
        with self.assertRaises(ValueError):
            Rule("DAILY", byday=(0,))
        with self.assertRaises(ValueError):
            Rule("WEEKLY", byday=(7,))
        self.assertEqual(Rule("WEEKLY", byday=(1,)).byday, (1,))

    def test_exdate(self):
        r = parse_rule("FREQ=DAILY;EXDATE=2024-01-05,2024-01-02")
        self.assertEqual(r.exdates, frozenset({D(2024, 1, 5), D(2024, 1, 2)}))
        with self.assertRaises(ValueError):
            parse_rule("FREQ=DAILY;EXDATE=2024-13-01")
        with self.assertRaises(ValueError):
            parse_rule("FREQ=DAILY;EXDATE=2024-01-01,")

    def test_defaults(self):
        r = Rule("DAILY")
        self.assertEqual(r.byday, ())
        self.assertEqual(r.exdates, frozenset())

    def test_new_freqs(self):
        self.assertEqual(parse_rule("freq=monthly").freq, "MONTHLY")
        self.assertEqual(parse_rule("FREQ=YEARLY;INTERVAL=2").interval, 2)

    def test_old_errors_still_apply(self):
        for bad in ("", "FREQ=MONTHLY;;COUNT=2", "FREQ=YEARLY;COUNT=2;UNTIL=2025-01-01", "FREQ=SECONDLY",
                    "FREQ=MONTHLY;FOO=1", "FREQ=MONTHLY;INTERVAL=0"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_rule(bad)

    def test_format(self):
        s = "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE,SU;COUNT=6;EXDATE=2024-01-03,2024-02-01"
        self.assertEqual(format_rule(parse_rule(s)), s)
        self.assertEqual(format_rule(parse_rule("EXDATE=2024-03-01;BYDAY=FR,mo;freq=weekly;UNTIL=2024-06-01")),
                         "FREQ=WEEKLY;BYDAY=MO,FR;UNTIL=2024-06-01;EXDATE=2024-03-01")
        self.assertEqual(format_rule(parse_rule("FREQ=MONTHLY")), "FREQ=MONTHLY")
        self.assertEqual(format_rule(Rule("YEARLY", exdates=frozenset({D(2025, 2, 1)}))), "FREQ=YEARLY;EXDATE=2025-02-01")


class WeeklyByDay(unittest.TestCase):
    def test_basic_week(self):
        # 2024-01-01 is a Monday
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=5", D(2024, 1, 1)),
                         [D(2024, 1, 1), D(2024, 1, 3), D(2024, 1, 5), D(2024, 1, 8), D(2024, 1, 10)])

    def test_start_mid_week_skips_earlier_days(self):
        # start Wednesday 2024-01-03: Monday of that week is skipped
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=MO,WE,FR", D(2024, 1, 3), 4),
                         [D(2024, 1, 3), D(2024, 1, 5), D(2024, 1, 8), D(2024, 1, 10)])

    def test_skipped_days_do_not_count(self):
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=MO,WE,FR;COUNT=2", D(2024, 1, 4)),
                         [D(2024, 1, 5), D(2024, 1, 8)])

    def test_start_not_in_byday_is_not_included(self):
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=TU", D(2024, 1, 3), 2), [D(2024, 1, 9), D(2024, 1, 16)])

    def test_interval_counts_weeks_from_start_week(self):
        # start Sunday 2024-01-07 (week of Mon Jan 1); interval 2 -> weeks of Jan 1, Jan 15, Jan 29
        self.assertEqual(occ("FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO", D(2024, 1, 7), 5),
                         [D(2024, 1, 7), D(2024, 1, 15), D(2024, 1, 21), D(2024, 1, 29), D(2024, 2, 4)])

    def test_week_starts_on_monday(self):
        # Sunday start, byday MO: Monday of the *same* week is before start, next is a week later
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=MO,SU", D(2024, 1, 7), 3),
                         [D(2024, 1, 7), D(2024, 1, 8), D(2024, 1, 14)])

    def test_byday_given_unsorted(self):
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=FR,MO;COUNT=3", D(2024, 1, 1)),
                         [D(2024, 1, 1), D(2024, 1, 5), D(2024, 1, 8)])

    def test_until_inclusive_with_byday(self):
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=2024-01-10", D(2024, 1, 1)),
                         [D(2024, 1, 1), D(2024, 1, 3), D(2024, 1, 8), D(2024, 1, 10)])

    def test_no_byday_still_start_weekday(self):
        self.assertEqual(occ("FREQ=WEEKLY;COUNT=3", D(2024, 1, 3)), [D(2024, 1, 3), D(2024, 1, 10), D(2024, 1, 17)])

    def test_year_boundary(self):
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=TU,TH;COUNT=3", D(2024, 12, 30)),
                         [D(2024, 12, 31), D(2025, 1, 2), D(2025, 1, 7)])


class Monthly(unittest.TestCase):
    def test_clamps_from_original_day(self):
        self.assertEqual(occ("FREQ=MONTHLY;COUNT=5", D(2024, 1, 31)),
                         [D(2024, 1, 31), D(2024, 2, 29), D(2024, 3, 31), D(2024, 4, 30), D(2024, 5, 31)])

    def test_non_leap_february(self):
        self.assertEqual(occ("FREQ=MONTHLY;COUNT=3", D(2023, 1, 30)), [D(2023, 1, 30), D(2023, 2, 28), D(2023, 3, 30)])

    def test_interval_and_year_rollover(self):
        self.assertEqual(occ("FREQ=MONTHLY;INTERVAL=5;COUNT=4", D(2024, 8, 15)),
                         [D(2024, 8, 15), D(2025, 1, 15), D(2025, 6, 15), D(2025, 11, 15)])

    def test_interval_twelve(self):
        self.assertEqual(occ("FREQ=MONTHLY;INTERVAL=12;COUNT=3", D(2024, 2, 29)),
                         [D(2024, 2, 29), D(2025, 2, 28), D(2026, 2, 28)])

    def test_until(self):
        self.assertEqual(occ("FREQ=MONTHLY;UNTIL=2024-03-31", D(2024, 1, 31)),
                         [D(2024, 1, 31), D(2024, 2, 29), D(2024, 3, 31)])
        self.assertEqual(occ("FREQ=MONTHLY;UNTIL=2024-03-30", D(2024, 1, 31)), [D(2024, 1, 31), D(2024, 2, 29)])


class Yearly(unittest.TestCase):
    def test_leap_day(self):
        self.assertEqual(occ("FREQ=YEARLY;COUNT=5", D(2024, 2, 29)),
                         [D(2024, 2, 29), D(2025, 2, 28), D(2026, 2, 28), D(2027, 2, 28), D(2028, 2, 29)])

    def test_interval_four_returns_to_leap(self):
        self.assertEqual(occ("FREQ=YEARLY;INTERVAL=4;COUNT=3", D(2024, 2, 29)),
                         [D(2024, 2, 29), D(2028, 2, 29), D(2032, 2, 29)])

    def test_plain(self):
        self.assertEqual(occ("FREQ=YEARLY;INTERVAL=10;COUNT=3", D(2000, 5, 17)),
                         [D(2000, 5, 17), D(2010, 5, 17), D(2020, 5, 17)])

    def test_stops_at_date_max(self):
        got = occ("FREQ=YEARLY;INTERVAL=3000", D(2000, 1, 1))
        self.assertEqual(got, [D(2000, 1, 1), D(5000, 1, 1), D(8000, 1, 1)])

    def test_monthly_stops_at_date_max(self):
        got = occ("FREQ=MONTHLY;INTERVAL=1200", D(9800, 1, 1))
        self.assertEqual(got, [D(9800, 1, 1), D(9900, 1, 1)])


class Exdates(unittest.TestCase):
    def test_removed(self):
        self.assertEqual(occ("FREQ=DAILY;COUNT=5;EXDATE=2024-01-02,2024-01-04", D(2024, 1, 1)),
                         [D(2024, 1, 1), D(2024, 1, 3), D(2024, 1, 5)])

    def test_count_includes_excluded(self):
        self.assertEqual(occ("FREQ=DAILY;COUNT=2;EXDATE=2024-01-01", D(2024, 1, 1)), [D(2024, 1, 2)])

    def test_nonoccurrence_exdate_ignored(self):
        self.assertEqual(occ("FREQ=WEEKLY;COUNT=2;EXDATE=2024-01-02", D(2024, 1, 1)), [D(2024, 1, 1), D(2024, 1, 8)])

    def test_with_weekly_byday_and_monthly(self):
        self.assertEqual(occ("FREQ=WEEKLY;BYDAY=MO,TU;COUNT=4;EXDATE=2024-01-02", D(2024, 1, 1)),
                         [D(2024, 1, 1), D(2024, 1, 8), D(2024, 1, 9)])
        self.assertEqual(occ("FREQ=MONTHLY;COUNT=3;EXDATE=2024-02-29", D(2024, 1, 31)), [D(2024, 1, 31), D(2024, 3, 31)])

    def test_unbounded_with_exdate_is_lazy(self):
        got = occ("FREQ=DAILY;EXDATE=2024-01-02", D(2024, 1, 1), 3)
        self.assertEqual(got, [D(2024, 1, 1), D(2024, 1, 3), D(2024, 1, 4)])


class Between(unittest.TestCase):
    def test_inclusive_bounds(self):
        r = parse_rule("FREQ=WEEKLY;BYDAY=MO,TH")
        self.assertEqual(between(r, D(2024, 1, 1), D(2024, 1, 4), D(2024, 1, 15)),
                         [D(2024, 1, 4), D(2024, 1, 8), D(2024, 1, 11), D(2024, 1, 15)])

    def test_unbounded_monthly(self):
        r = parse_rule("FREQ=MONTHLY")
        self.assertEqual(between(r, D(2024, 1, 31), D(2030, 1, 1), D(2030, 3, 31)),
                         [D(2030, 1, 31), D(2030, 2, 28), D(2030, 3, 31)])

    def test_excludes_exdates(self):
        r = parse_rule("FREQ=DAILY;EXDATE=2024-01-03")
        self.assertEqual(between(r, D(2024, 1, 1), D(2024, 1, 2), D(2024, 1, 4)), [D(2024, 1, 2), D(2024, 1, 4)])


if __name__ == "__main__":
    unittest.main()
