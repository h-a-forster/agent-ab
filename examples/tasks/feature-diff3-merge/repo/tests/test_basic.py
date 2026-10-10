import unittest

from textmerge import MergeConflict, apply_diff, diff, merge_text, split_lines


class Basics(unittest.TestCase):
    def test_split_lines(self):
        self.assertEqual(split_lines("a\nb\n"), ["a\n", "b\n"])
        self.assertEqual(split_lines("a\nb"), ["a\n", "b"])
        self.assertEqual(split_lines(""), [])
        self.assertEqual(split_lines("a\x0cb\r\nc"), ["a\x0cb\r\n", "c"])

    def test_diff_roundtrip(self):
        a = ["a\n", "b\n", "c\n", "d\n"]
        b = ["a\n", "c\n", "x\n", "d\n", "e\n"]
        ops = diff(a, b)
        self.assertEqual(apply_diff(a, ops), b)
        self.assertEqual(sum(1 for o, _ in ops if o == "="), 3)

    def test_apply_diff_rejects_mismatch(self):
        with self.assertRaises(ValueError):
            apply_diff(["a\n"], [("=", "b\n")])

    def test_merge_file_level(self):
        self.assertEqual(merge_text("a\n", "a\n", "b\n"), "b\n")
        self.assertEqual(merge_text("a\n", "b\n", "a\n"), "b\n")
        self.assertEqual(merge_text("a\n", "b\n", "b\n"), "b\n")
        with self.assertRaises(MergeConflict):
            merge_text("a\n", "b\n", "c\n")
