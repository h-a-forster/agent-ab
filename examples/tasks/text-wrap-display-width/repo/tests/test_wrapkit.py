import unittest

from wrapkit import display_width, render_table, strip_ansi, truncate, wrap


class Basics(unittest.TestCase):
    def test_width_ascii(self):
        self.assertEqual(display_width("hello"), 5)
        self.assertEqual(display_width(""), 0)

    def test_strip(self):
        self.assertEqual(strip_ansi("\x1b[31mred\x1b[0m"), "red")

    def test_wrap(self):
        self.assertEqual(wrap("the quick brown fox", 10), ["the quick", "brown fox"])
        self.assertEqual(wrap("a\n\nb", 5), ["a", "", "b"])
        self.assertEqual(wrap("  spaced   out  ", 20), ["spaced out"])

    def test_wrap_overflow_ascii_word_alone(self):
        self.assertEqual(wrap("ab", 5), ["ab"])

    def test_wrap_bad_width(self):
        with self.assertRaises(ValueError):
            wrap("x", 0)

    def test_table(self):
        self.assertEqual(render_table([["a", "b c d"]], [3, 3]), "a   | b c\n    | d")
        self.assertEqual(render_table([["x", "y"]], [3, 3], "rc"), "  x |  y")

    def test_table_errors(self):
        with self.assertRaises(ValueError):
            render_table([["a", "b", "c"]], [3, 3])

    def test_truncate(self):
        self.assertEqual(truncate("hello world", 8), "hello...")
        self.assertEqual(truncate("short", 8), "short")
        with self.assertRaises(ValueError):
            truncate("abcdef", 2)


if __name__ == "__main__":
    unittest.main()
