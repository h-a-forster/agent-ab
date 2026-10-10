import unittest

from ivl import Interval, format_interval, gaps, intersect, merge, parse, subtract, total_length

C, O = True, False


def iv(lo, hi, lc=True, hc=False):
    return Interval(lo, hi, lc, hc)


class Construction(unittest.TestCase):
    def test_defaults(self):
        i = Interval(1, 2)
        self.assertTrue(i.lo_closed)
        self.assertFalse(i.hi_closed)
        self.assertEqual(i, Interval(1, 2, True, False))

    def test_flags_in_equality(self):
        self.assertNotEqual(Interval(1, 2), Interval(1, 2, True, True))
        self.assertNotEqual(Interval(1, 2), Interval(1, 2, False, False))

    def test_point_allowed_only_when_closed(self):
        self.assertEqual(iv(5, 5, C, C).lo, 5)
        for lc, hc in ((C, O), (O, C), (O, O)):
            with self.assertRaises(ValueError):
                iv(5, 5, lc, hc)

    def test_reversed_rejected(self):
        with self.assertRaises(ValueError):
            iv(3, 2, C, C)

    def test_frozen_hashable(self):
        self.assertEqual(len({iv(1, 2), iv(1, 2), iv(1, 2, C, C)}), 2)


class Membership(unittest.TestCase):
    def test_contains_each_flag_combo(self):
        self.assertTrue(iv(1, 3, C, C).contains(1))
        self.assertTrue(iv(1, 3, C, C).contains(3))
        self.assertFalse(iv(1, 3, O, O).contains(1))
        self.assertFalse(iv(1, 3, O, O).contains(3))
        self.assertTrue(iv(1, 3, O, O).contains(2))
        self.assertTrue(iv(1, 3, O, C).contains(3))
        self.assertFalse(iv(1, 3, C, O).contains(3))

    def test_contains_point_interval(self):
        p = iv(5, 5, C, C)
        self.assertTrue(p.contains(5))
        self.assertFalse(p.contains(4.999))
        self.assertFalse(p.contains(5.001))

    def test_overlaps(self):
        self.assertFalse(iv(1, 2).overlaps(iv(2, 3)))
        self.assertTrue(iv(1, 2, C, C).overlaps(iv(2, 3)))
        self.assertFalse(iv(1, 2, C, C).overlaps(iv(2, 3, O, O)))
        self.assertTrue(iv(2, 2, C, C).overlaps(iv(1, 3)))
        self.assertFalse(iv(2, 2, C, C).overlaps(iv(2, 3, O, O)))
        self.assertTrue(iv(1, 5).overlaps(iv(2, 3)))


class Intersect(unittest.TestCase):
    def test_equal_lower_bounds(self):
        self.assertEqual(intersect(iv(1, 5, C, O), iv(1, 4, O, O)), iv(1, 4, O, O))
        self.assertEqual(intersect(iv(1, 5, C, O), iv(1, 4, C, O)), iv(1, 4, C, O))

    def test_equal_upper_bounds(self):
        self.assertEqual(intersect(iv(0, 5, C, C), iv(2, 5, C, O)), iv(2, 5, C, O))
        self.assertEqual(intersect(iv(0, 5, C, C), iv(2, 5, C, C)), iv(2, 5, C, C))

    def test_touching_yields_point_or_none(self):
        self.assertEqual(intersect(iv(1, 3, C, C), iv(3, 6)), iv(3, 3, C, C))
        self.assertIsNone(intersect(iv(1, 3, C, O), iv(3, 6)))
        self.assertIsNone(intersect(iv(1, 3, C, C), iv(3, 6, O, O)))

    def test_disjoint(self):
        self.assertIsNone(intersect(iv(1, 2), iv(5, 6)))


class Subtract(unittest.TestCase):
    def test_middle_cut_flips_flags(self):
        self.assertEqual(subtract(iv(0, 10), iv(3, 5)), [iv(0, 3), iv(5, 10)])
        self.assertEqual(subtract(iv(0, 10), iv(3, 5, O, C)), [iv(0, 3, C, C), iv(5, 10, O, O)])

    def test_remove_point(self):
        self.assertEqual(subtract(iv(0, 10), iv(5, 5, C, C)), [iv(0, 5), iv(5, 10, O, O)])

    def test_remove_everything(self):
        self.assertEqual(subtract(iv(2, 4), iv(0, 10)), [])
        self.assertEqual(subtract(iv(2, 4, C, C), iv(2, 4, C, C)), [])

    def test_leaves_endpoint_behind(self):
        self.assertEqual(subtract(iv(2, 4, C, C), iv(2, 4, O, O)), [iv(2, 2, C, C), iv(4, 4, C, C)])

    def test_disjoint_returns_a(self):
        self.assertEqual(subtract(iv(0, 2), iv(5, 6)), [iv(0, 2)])
        self.assertEqual(subtract(iv(5, 6), iv(0, 2)), [iv(5, 6)])
        self.assertEqual(subtract(iv(0, 2), iv(2, 4)), [iv(0, 2)])

    def test_one_sided(self):
        self.assertEqual(subtract(iv(0, 10), iv(0, 4)), [iv(4, 10)])
        self.assertEqual(subtract(iv(0, 10), iv(0, 4, O, O)), [iv(0, 0, C, C), iv(4, 10)])
        self.assertEqual(subtract(iv(0, 10), iv(6, 20)), [iv(0, 6, C, O)])
        self.assertEqual(subtract(iv(0, 10, C, C), iv(6, 20)), [iv(0, 6, C, O)])


class Merge(unittest.TestCase):
    def test_adjacent_half_open_join(self):
        self.assertEqual(merge([iv(2, 3), iv(1, 2)]), [iv(1, 3)])

    def test_gap_point_keeps_separate(self):
        self.assertEqual(merge([iv(1, 2), iv(2, 3, O, O)]), [iv(1, 2), iv(2, 3, O, O)])

    def test_closed_open_join(self):
        self.assertEqual(merge([iv(1, 2, C, C), iv(2, 3, O, O)]), [iv(1, 3, C, O)])

    def test_overlap_takes_wider_flags(self):
        self.assertEqual(merge([iv(1, 5, O, O), iv(1, 4, C, O)]), [iv(1, 5, C, O)])
        self.assertEqual(merge([iv(1, 5, C, O), iv(2, 5, C, C)]), [iv(1, 5, C, C)])

    def test_sort_order_closed_first(self):
        self.assertEqual(merge([iv(3, 4, O, O), iv(3, 3, C, C), iv(7, 8)]), [iv(3, 4, C, O), iv(7, 8)])

    def test_points_merge_into_interval(self):
        self.assertEqual(merge([iv(1, 1, C, C), iv(1, 3, O, O)]), [iv(1, 3, C, O)])

    def test_contained_and_empty_input(self):
        self.assertEqual(merge([iv(0, 10, C, C), iv(2, 3)]), [iv(0, 10, C, C)])
        self.assertEqual(merge([]), [])

    def test_does_not_mutate_input(self):
        data = [iv(5, 6), iv(1, 2)]
        merge(data)
        self.assertEqual(data, [iv(5, 6), iv(1, 2)])


class GapsAndLength(unittest.TestCase):
    def test_gaps_flags(self):
        self.assertEqual(gaps([iv(2, 4, C, C)], iv(0, 10)), [iv(0, 2), iv(4, 10, O, O)])

    def test_gaps_multiple_and_unordered(self):
        got = gaps([iv(6, 7), iv(1, 2), iv(1.5, 3)], iv(0, 10, C, C))
        self.assertEqual(got, [iv(0, 1), iv(3, 6), iv(7, 10, C, C)])

    def test_gaps_fully_covered(self):
        self.assertEqual(gaps([iv(0, 10, C, C)], iv(1, 5)), [])

    def test_gaps_empty_cover(self):
        self.assertEqual(gaps([], iv(0, 3, O, C)), [iv(0, 3, O, C)])

    def test_gaps_open_window_ends(self):
        self.assertEqual(gaps([iv(0, 5, C, C)], iv(0, 8, O, O)), [iv(5, 8, O, O)])

    def test_total_length(self):
        self.assertEqual(total_length([iv(0, 2, C, C), iv(2, 4, O, O), iv(10, 11)]), 5)
        self.assertEqual(total_length([iv(3, 3, C, C)]), 0)
        self.assertEqual(total_length([]), 0)


class Text(unittest.TestCase):
    def test_format_all_combos(self):
        self.assertEqual(str(iv(1, 5)), "[1, 5)")
        self.assertEqual(str(iv(1, 5, O, C)), "(1, 5]")
        self.assertEqual(str(iv(1, 5, O, O)), "(1, 5)")
        self.assertEqual(format_interval(iv(3, 3, C, C)), "[3, 3]")
        self.assertEqual(format_interval(iv(0.5, 2, C, C)), "[0.5, 2]")

    def test_parse_all_combos(self):
        self.assertEqual(parse("[1, 5)"), iv(1, 5))
        self.assertEqual(parse("(1,5]"), iv(1, 5, O, C))
        self.assertEqual(parse(" ( 1 , 5 ) "), iv(1, 5, O, O))
        self.assertEqual(parse("[-2.5,3]"), iv(-2.5, 3, C, C))
        self.assertEqual(parse("[4,4]"), iv(4, 4, C, C))

    def test_parse_number_types(self):
        a = parse("[1, 2.5)")
        self.assertIsInstance(a.lo, int)
        self.assertIsInstance(a.hi, float)

    def test_parse_invalid(self):
        for bad in ("", "1,5", "[1;5)", "[1, 5", "[4,4)", "(4,4]", "[5,1]", "[a,b]", "{1,2}", "[1,2,3)"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse(bad)

    def test_roundtrip(self):
        for s in ("[1, 5)", "(1, 5]", "(0.5, 9)", "[2, 2]"):
            self.assertEqual(str(parse(s)), s)


if __name__ == "__main__":
    unittest.main()
