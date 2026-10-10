import unittest

from layout import format_paragraph, format_text, justify_words, wrap

TEXT = "the quick brown fox jumps over the lazy dog and keeps running far away"


class Basics(unittest.TestCase):
    def test_wrap_greedy(self):
        self.assertEqual(wrap("aaa bb c dddd".split(), 6), [["aaa", "bb"], ["c", "dddd"]])
        self.assertEqual(wrap(["abcdefghij", "k"], 4), [["abcdefghij"], ["k"]])
        self.assertEqual(wrap([], 5), [])

    def test_left(self):
        self.assertEqual(format_paragraph(TEXT, 20),
                         ["the quick brown fox", "jumps over the lazy", "dog and keeps", "running far away"])
        self.assertEqual(format_paragraph("aa bb cc", 5), ["aa bb", "cc"])
        self.assertEqual(format_paragraph("   ", 5), [])

    def test_justify(self):
        self.assertEqual(justify_words(["a", "b", "c"], 8), "a   b  c")
        self.assertEqual(format_paragraph("aa bb cc dd", 7, "justify"), ["aa   bb", "cc dd"])

    def test_right_center_indent(self):
        self.assertEqual(format_paragraph("aa bb cc", 5, "right"), ["aa bb", "   cc"])
        self.assertEqual(format_paragraph("aa bb cc", 7, "center"), [" aa bb", "  cc"])
        self.assertEqual(format_paragraph("aa bb cc", 7, indent=2), ["  aa bb", "  cc"])

    def test_text(self):
        self.assertEqual(format_text("aa bb\n\n\n  \ncc dd ee", 5), "aa bb\n\ncc dd\nee")
        self.assertEqual(format_text("   \n\n", 5), "")

    def test_errors(self):
        with self.assertRaises(ValueError):
            format_paragraph("a b", 0)
        with self.assertRaises(ValueError):
            format_paragraph("a b", 5, indent=5)
        with self.assertRaises(ValueError):
            format_paragraph("a b", 5, indent=-1)
        with self.assertRaises(ValueError):
            format_paragraph("a b", 5, align="zigzag")
