import unittest
from datetime import date, datetime, timedelta, timezone

from sessions import Event, EventError, daily_report, load_events, sessionize

UTC = timezone.utc


def ev(user, minute, type="view", value=0.0, hour=10, day=1):
    return Event(datetime(2024, 3, day, hour, minute, tzinfo=UTC), user, type, value)


class LoaderTests(unittest.TestCase):
    def test_load(self):
        lines = ['{"ts": "2024-03-01T10:00:00Z", "user": "u1", "type": "click", "value": 2}\n', "\n",
                 '{"ts": "2024-03-01T10:05:00Z", "user": "u2"}\n']
        events = load_events(lines)
        self.assertEqual(events[0], Event(datetime(2024, 3, 1, 10, 0, tzinfo=UTC), "u1", "click", 2))
        self.assertEqual(events[1].type, "event")

    def test_errors_have_line_numbers(self):
        with self.assertRaises(EventError) as ctx:
            load_events(['{"ts": "2024-03-01T10:00:00Z", "user": "u"}', "", "not json"])
        self.assertEqual(ctx.exception.line, 3)
        with self.assertRaises(EventError):
            load_events(['{"user": "u"}'])


class SessionTests(unittest.TestCase):
    def test_split_on_gap(self):
        sessions = sessionize([ev("a", 0), ev("a", 10), ev("a", 50), ev("b", 5)])
        self.assertEqual([(s.user, s.count) for s in sessions], [("a", 2), ("b", 1), ("a", 1)])

    def test_session_fields(self):
        (s,) = sessionize([ev("a", 5), ev("a", 0)])
        self.assertEqual(s.start, datetime(2024, 3, 1, 10, 0, tzinfo=UTC))
        self.assertEqual(s.duration, timedelta(minutes=5))


class ReportTests(unittest.TestCase):
    def test_report(self):
        sessions = sessionize([ev("a", 0, value=1), ev("a", 10, value=2), ev("b", 0), ev("a", 0, day=2)])
        rows = daily_report(sessions)
        self.assertEqual([r.day for r in rows], [date(2024, 3, 1), date(2024, 3, 2)])
        self.assertEqual((rows[0].sessions, rows[0].users, rows[0].events), (2, 2, 3))
        self.assertEqual(rows[0].total_seconds, 600)
        self.assertEqual(rows[0].avg_events, 1.5)
        self.assertEqual(rows[0].total_value, 3)


if __name__ == "__main__":
    unittest.main()
