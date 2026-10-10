import unittest
from datetime import date, datetime, timedelta, timezone

from sessions import (DayStats, Event, EventError, daily_report, load_events, load_lenient,
                      sessionize)

UTC = timezone.utc
MIN = timedelta(minutes=1)


def at(minute, hour=10, day=1, month=3):
    return datetime(2024, month, day, hour, 0, tzinfo=UTC) + timedelta(minutes=minute)


def m(dt):
    return int((dt - at(0)) / MIN)


def ev(user, minute, type="view", value=0.0, hour=10, day=1):
    return Event(at(minute, hour, day), user, type, value)


def line(**kw):
    import json
    return json.dumps(kw)


def one(**kw):
    (e,) = load_events([line(user="u", **kw)])
    return e


class TimestampParsing(unittest.TestCase):
    def test_z_and_offsets(self):
        self.assertEqual(one(ts="2024-03-01T10:00:00Z").ts, at(0))
        self.assertEqual(one(ts="2024-03-01T12:00:00+02:00").ts, at(0))
        self.assertEqual(one(ts="2024-03-01T05:30:00-04:30").ts, at(0))
        self.assertEqual(one(ts="2024-03-01T12:00:00+02:00").ts.utcoffset(), timedelta(0))

    def test_naive_is_utc(self):
        e = one(ts="2024-03-01T10:00:00")
        self.assertEqual(e.ts, at(0))
        self.assertIsNotNone(e.ts.tzinfo)
        self.assertEqual(one(ts="2024-03-01 10:00:00").ts, at(0))

    def test_fractional_and_date_only(self):
        self.assertEqual(one(ts="2024-03-01T10:00:00.250Z").ts, at(0) + timedelta(milliseconds=250))
        self.assertEqual(one(ts="2024-03-01").ts, datetime(2024, 3, 1, tzinfo=UTC))

    def test_epoch_numbers(self):
        base = int(at(0).timestamp())
        self.assertEqual(one(ts=base).ts, at(0))
        self.assertEqual(one(ts=base + 0.5).ts, at(0) + timedelta(milliseconds=500))
        self.assertEqual(one(ts=0).ts, datetime(1970, 1, 1, tzinfo=UTC))

    def test_bad_timestamps(self):
        bad = ['"yesterday"', "true", "null", "[]", "{}", '"2024-13-01T00:00:00Z"', "1e999", "NaN", "Infinity",
               "1e30", '""']
        for ts in bad:
            with self.assertRaises(EventError, msg=ts):
                load_events(['{"ts": %s, "user": "u"}' % ts])
        with self.assertRaises(EventError):
            load_events(['{"user": "u"}'])


class FieldValidation(unittest.TestCase):
    def test_defaults(self):
        e = one(ts=0)
        self.assertEqual((e.type, e.value), ("event", 0))

    def test_good_values(self):
        e = one(ts=0, type="click", value=-2.5)
        self.assertEqual((e.type, e.value), ("click", -2.5))
        self.assertEqual(one(ts=0, value=3).value, 3)

    def test_bad_values(self):
        for kw in ({"value": "3"}, {"value": True}, {"value": None}, {"value": [1]}, {"type": 5}, {"type": ""},
                   {"type": None}):
            with self.assertRaises(EventError, msg=str(kw)):
                load_events([line(ts=0, user="u", **kw)])
        for raw in ("NaN", "Infinity", "-Infinity"):
            with self.assertRaises(EventError, msg=raw):
                load_events(['{"ts": 0, "user": "u", "value": %s}' % raw])

    def test_bad_user(self):
        for user in ("", 5, None, ["a"]):
            with self.assertRaises(EventError):
                load_events([line(ts=0, user=user)])
        with self.assertRaises(EventError):
            load_events([line(ts=0)])

    def test_not_objects(self):
        for text in ("[]", '"x"', "5", "null", "{bad json"):
            with self.assertRaises(EventError, msg=text):
                load_events([text])

    def test_extra_fields_ignored(self):
        self.assertEqual(len(load_events([line(ts=0, user="u", extra=[1, 2])])), 1)


class Lenient(unittest.TestCase):
    LINES = [
        line(ts="2024-03-01T10:00:00Z", user="a"),
        "",
        "nope",
        line(ts=5, user="b", value=1),
        "   \n",
        line(ts="bad", user="c"),
        line(ts=0, user="d", value=True),
        line(ts=0, user="e") + "\n",
    ]

    def test_collects_errors_with_lines(self):
        events, errors = load_lenient(self.LINES)
        self.assertEqual([e.user for e in events], ["a", "b", "e"])
        self.assertEqual([e.line for e in errors], [3, 6, 7])
        self.assertTrue(all(isinstance(e, EventError) for e in errors))

    def test_strict_reports_first_error(self):
        with self.assertRaises(EventError) as ctx:
            load_events(self.LINES)
        self.assertEqual(ctx.exception.line, 3)

    def test_all_good_and_empty(self):
        self.assertEqual(load_lenient([]), ([], []))
        events, errors = load_lenient([line(ts=0, user="x")])
        self.assertEqual((len(events), errors), (1, []))

    def test_accepts_generators(self):
        events, errors = load_lenient(l for l in self.LINES)
        self.assertEqual((len(events), len(errors)), (3, 3))


class Splitting(unittest.TestCase):
    def test_gap_is_strict(self):
        s = sessionize([ev("a", 0), ev("a", 30)])
        self.assertEqual(len(s), 1)
        s = sessionize([ev("a", 0), ev("a", 31)])
        self.assertEqual(len(s), 2)
        s = sessionize([ev("a", 0), ev("a", 5)], gap=5 * MIN)
        self.assertEqual(len(s), 1)

    def test_gap_measured_from_previous_event(self):
        events = [ev("a", m) for m in (0, 25, 50, 75, 100)]
        (s,) = sessionize(events)
        self.assertEqual(s.count, 5)
        self.assertEqual(s.duration, 100 * MIN)

    def test_out_of_order_input(self):
        events = [ev("a", 50), ev("a", 0), ev("a", 25), ev("a", 75)]
        s = sessionize(events)
        self.assertEqual([x.count for x in s], [4])
        self.assertEqual([m(e.ts) for e in s[0].events], [0, 25, 50, 75])

    def test_users_are_independent(self):
        events = [ev("a", 0), ev("b", 1), ev("a", 10), ev("b", 50), ev("a", 20)]
        s = sessionize(events)
        self.assertEqual({(x.user, x.count) for x in s}, {("a", 3), ("b", 1)} | {("b", 1)})
        self.assertEqual(len(s), 3)

    def test_max_duration(self):
        events = [ev("a", m) for m in range(0, 60, 10)]
        s = sessionize(events, max_duration=25 * MIN)
        self.assertEqual([x.count for x in s], [3, 3])
        self.assertEqual([m(x.start) for x in s], [0, 30])
        s = sessionize(events, max_duration=30 * MIN)
        self.assertEqual([x.count for x in s], [4, 2])
        s = sessionize(events, max_duration=50 * MIN)
        self.assertEqual([x.count for x in s], [6])

    def test_max_duration_restarts_from_new_first_event(self):
        events = [ev("a", m) for m in (0, 10, 20, 30, 40, 50, 60 + 0)]
        events[-1] = ev("a", 0, hour=11)
        s = sessionize(events, max_duration=20 * MIN)
        self.assertEqual([x.count for x in s], [3, 3, 1])

    def test_gap_and_max_duration_combined(self):
        events = [ev("a", 0), ev("a", 10), ev("a", 20), ev("a", 55), ev("a", 60), ev("a", 70)]
        s = sessionize(events, gap=30 * MIN, max_duration=100 * MIN)
        self.assertEqual([x.count for x in s], [3, 3])
        s = sessionize(events, gap=40 * MIN, max_duration=15 * MIN)
        self.assertEqual([x.count for x in s], [2, 1, 3])

    def test_invalid_parameters(self):
        for kw in ({"gap": timedelta(0)}, {"gap": -MIN}, {"max_duration": timedelta(0)}, {"max_duration": -MIN}):
            with self.assertRaises(ValueError, msg=str(kw)):
                sessionize([ev("a", 0)], **kw)

    def test_empty_input(self):
        self.assertEqual(sessionize([]), [])


class FilteringAndDuplicates(unittest.TestCase):
    def test_exact_duplicates_dropped_first_kept(self):
        events = [ev("a", 0, "view", 1), ev("a", 0, "view", 99), ev("a", 0, "click", 5), ev("a", 1, "view", 2)]
        (s,) = sessionize(events)
        self.assertEqual([(e.type, e.value) for e in s.events], [("view", 1), ("click", 5), ("view", 2)])

    def test_duplicates_across_users_are_distinct(self):
        s = sessionize([ev("a", 0), ev("b", 0)])
        self.assertEqual(len(s), 2)

    def test_equal_ts_keep_input_order(self):
        events = [ev("a", 0, "z"), ev("a", 0, "b"), ev("a", 0, "m")]
        (s,) = sessionize(events)
        self.assertEqual([e.type for e in s.events], ["z", "b", "m"])

    def test_types_filter(self):
        events = [ev("a", 0, "view"), ev("a", 5, "click"), ev("a", 50, "view"), ev("a", 55, "click")]
        s = sessionize(events, types={"click"})
        self.assertEqual([x.count for x in s], [1, 1])
        s = sessionize(events, types=["view", "click"])
        self.assertEqual([x.count for x in s], [2, 2])
        self.assertEqual(sessionize(events, types=[]), [])
        self.assertEqual(sessionize(events, types={"nope"}), [])

    def test_filter_applies_before_gap(self):
        events = [ev("a", 0, "view"), ev("a", 20, "click"), ev("a", 40, "view")]
        s = sessionize(events, types={"view"})
        self.assertEqual([x.count for x in s], [1, 1])
        self.assertEqual(len(sessionize(events)), 1)


class Ordering(unittest.TestCase):
    def test_ids_per_user_in_time_order(self):
        events = [ev("b", 0), ev("a", 100), ev("a", 0), ev("a", 200), ev("b", 150)]
        s = sessionize(events)
        ids = {(x.user, m(x.start)): x.id for x in s}
        self.assertEqual(ids[("a", 0)], "a#1")
        self.assertEqual(ids[("a", 100)], "a#2")
        self.assertEqual(ids[("a", 200)], "a#3")
        self.assertEqual(ids[("b", 0)], "b#1")
        self.assertEqual(ids[("b", 150)], "b#2")

    def test_sorted_by_start_then_user(self):
        events = [ev("z", 0), ev("a", 0), ev("m", 5), ev("a", 100), ev("b", 50)]
        s = sessionize(events)
        self.assertEqual([(m(x.start), x.user) for x in s],
                         [(0, "a"), (0, "z"), (5, "m"), (50, "b"), (100, "a")])

    def test_session_fields(self):
        (s,) = sessionize([ev("a", 7, value=2), ev("a", 3, value=1)])
        self.assertEqual((s.start, s.end), (at(3), at(7)))
        self.assertEqual(s.duration, 4 * MIN)
        self.assertEqual([e.value for e in s.events], [1, 2])
        self.assertIsInstance(s.events, tuple)

    def test_does_not_mutate_input(self):
        events = [ev("a", 50), ev("a", 0)]
        copy = list(events)
        sessionize(events)
        self.assertEqual(events, copy)

    def test_accepts_iterator(self):
        self.assertEqual(len(sessionize(iter([ev("a", 0), ev("b", 0)]))), 2)


class Report(unittest.TestCase):
    def sessions(self):
        return sessionize([
            ev("a", 0, value=1, hour=23, day=1), ev("a", 20, value=2, hour=23, day=1),
            ev("a", 40, value=3, hour=23, day=1), ev("a", 10, value=4, hour=0, day=2),
            ev("b", 0, value=5, hour=12, day=2),
        ], gap=45 * MIN)

    def test_session_attributed_to_start_day(self):
        s = self.sessions()
        self.assertEqual([(x.user, x.count) for x in s], [("a", 4), ("b", 1)])
        rows = daily_report(s)
        self.assertEqual([r.day for r in rows], [date(2024, 3, 1), date(2024, 3, 2)])
        first, second = rows
        self.assertEqual((first.sessions, first.users, first.events), (1, 1, 4))
        self.assertAlmostEqual(first.total_seconds, 70 * 60 + 0)
        self.assertEqual((second.sessions, second.users, second.events), (1, 1, 1))
        self.assertEqual(first.total_value, 10.0)
        self.assertEqual(second.total_value, 5.0)

    def test_offset_shifts_days(self):
        s = self.sessions()
        rows = daily_report(s, utc_offset=timedelta(hours=2))
        self.assertEqual([r.day for r in rows], [date(2024, 3, 2)])
        self.assertEqual((rows[0].sessions, rows[0].users, rows[0].events), (2, 2, 5))
        rows = daily_report(s, utc_offset=timedelta(hours=-11, minutes=-30))
        self.assertEqual([r.day for r in rows], [date(2024, 3, 1), date(2024, 3, 2)])
        self.assertEqual([r.sessions for r in rows], [1, 1])
        rows = daily_report(s, utc_offset=timedelta(hours=0, minutes=59))
        self.assertEqual([r.day for r in rows], [date(2024, 3, 1), date(2024, 3, 2)])
        rows = daily_report(s, utc_offset=timedelta(hours=1))
        self.assertEqual([r.day for r in rows], [date(2024, 3, 2)])

    def test_offset_validation(self):
        for off in (timedelta(hours=24), timedelta(hours=-24), timedelta(hours=30)):
            with self.assertRaises(ValueError):
                daily_report([], utc_offset=off)
        self.assertEqual(daily_report([], utc_offset=timedelta(hours=23, minutes=59)), [])

    def test_stats(self):
        s = sessionize([ev("a", 0, value=1.5), ev("a", 10, value=2.5), ev("b", 0), ev("b", 1), ev("b", 2),
                        ev("c", 0, value=-1), ev("a", 100)])
        (row,) = daily_report(s)
        self.assertIsInstance(row, DayStats)
        self.assertEqual((row.sessions, row.users, row.events), (4, 3, 7))
        self.assertAlmostEqual(row.avg_events, 7 / 4)
        self.assertAlmostEqual(row.total_seconds, 10 * 60 + 2 * 60)
        self.assertAlmostEqual(row.total_value, 3.0)
        self.assertIsInstance(row.total_value, float)
        self.assertIsInstance(row.total_seconds, float)

    def test_users_counted_once_per_day(self):
        s = sessionize([ev("a", 0), ev("a", 100), ev("a", 200)])
        (row,) = daily_report(s)
        self.assertEqual((row.sessions, row.users), (3, 1))

    def test_empty_and_sorted(self):
        self.assertEqual(daily_report([]), [])
        s = sessionize([ev("a", 0, day=5), ev("a", 0, day=2), ev("a", 0, day=9)])
        self.assertEqual([r.day.day for r in daily_report(s)], [2, 5, 9])

    def test_end_to_end_with_loader(self):
        lines = [
            line(ts="2024-03-01T23:50:00Z", user="a", value=1),
            line(ts="2024-03-02T00:10:00+00:00", user="a", value=1),
            line(ts="2024-03-02T03:00:00+02:00", user="b"),
            "garbage",
            line(ts=int(datetime(2024, 3, 2, 12, tzinfo=UTC).timestamp()), user="b"),
        ]
        events, errors = load_lenient(lines)
        rows = daily_report(sessionize(events, gap=2 * timedelta(hours=1)))
        self.assertEqual(len(errors), 1)
        self.assertEqual([(r.day.day, r.sessions, r.events) for r in rows], [(1, 1, 2), (2, 2, 2)])


if __name__ == "__main__":
    unittest.main()
