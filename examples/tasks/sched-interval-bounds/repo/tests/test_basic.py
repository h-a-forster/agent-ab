import unittest

from ivl import Interval, format_interval, gaps, intersect, merge, parse, subtract, total_length


class Basics(unittest.TestCase):
    def test_empty_rejected(self):
        for lo, hi in ((1, 1), (3, 2)):
            with self.assertRaises(ValueError):
                Interval(lo, hi)

    def test_contains_half_open(self):
        iv = Interval(1, 3)
        self.assertTrue(iv.contains(1))
        self.assertFalse(iv.contains(3))

    def test_merge_touching(self):
        self.assertEqual(merge([Interval(3, 5), Interval(1, 3)]), [Interval(1, 5)])
        self.assertEqual(merge([Interval(1, 2), Interval(4, 5)]), [Interval(1, 2), Interval(4, 5)])

    def test_intersect(self):
        self.assertEqual(intersect(Interval(1, 5), Interval(3, 9)), Interval(3, 5))
        self.assertIsNone(intersect(Interval(1, 3), Interval(3, 9)))

    def test_subtract_and_gaps(self):
        self.assertEqual(subtract(Interval(0, 10), Interval(3, 5)), [Interval(0, 3), Interval(5, 10)])
        self.assertEqual(gaps([Interval(2, 4)], Interval(0, 10)), [Interval(0, 2), Interval(4, 10)])
        self.assertEqual(total_length([Interval(0, 2), Interval(1, 4)]), 4)

    def test_text(self):
        self.assertEqual(parse(" [1, 5) "), Interval(1, 5))
        self.assertEqual(format_interval(Interval(1, 2.5)), "[1, 2.5)")
        with self.assertRaises(ValueError):
            parse("1,5")


if __name__ == "__main__":
    unittest.main()
