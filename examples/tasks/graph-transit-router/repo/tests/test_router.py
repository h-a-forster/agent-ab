import unittest

from transit import Connection, Timetable, earliest_arrival


class Basics(unittest.TestCase):
    def setUp(self):
        self.tt = Timetable([
            Connection("A", "B", 480, 510, "T1"),
            Connection("B", "C", 510, 540, "T1"),
            Connection("B", "C", 520, 545, "T2"),
            Connection("A", "B", 600, 630, "T3"),
        ])

    def test_through_trip_is_one_leg(self):
        it = earliest_arrival(self.tt, "A", "C", 470)
        self.assertEqual((it.departure, it.arrival, len(it.legs), it.transfers), (480, 540, 1, 0))
        self.assertEqual(it.legs[0].trip, "T1")
        self.assertEqual((it.legs[0].src, it.legs[0].dst), ("A", "C"))

    def test_later_departure(self):
        it = earliest_arrival(self.tt, "A", "B", 481)
        self.assertEqual(it.arrival, 630)

    def test_unreachable(self):
        self.assertIsNone(earliest_arrival(self.tt, "C", "A", 0))
        self.assertIsNone(earliest_arrival(self.tt, "A", "Z", 0))

    def test_same_station(self):
        it = earliest_arrival(self.tt, "A", "A", 50)
        self.assertEqual((it.legs, it.arrival), ((), 50))

    def test_describe(self):
        self.assertEqual(earliest_arrival(self.tt, "A", "C", 0).describe(), "08:00 A -> 09:00 C [T1]")

    def test_validation(self):
        with self.assertRaises(ValueError):
            Connection("A", "A", 1, 2, "T")
        with self.assertRaises(ValueError):
            Connection("A", "B", 5, 5, "T")


if __name__ == "__main__":
    unittest.main()
