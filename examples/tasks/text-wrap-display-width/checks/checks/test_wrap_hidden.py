import unittest

from wrapkit import display_width, render_table, strip_ansi, truncate, wrap

R = "\x1b[0m"
RED = "\x1b[31m"
BOLD = "\x1b[1m"


class Width(unittest.TestCase):
    def test_ansi_is_zero(self):
        self.assertEqual(display_width(RED + "red" + R), 3)
        self.assertEqual(display_width("\x1b[1;31;4m"), 0)
        self.assertEqual(display_width("\x1b[m"), 0)

    def test_cjk(self):
        self.assertEqual(display_width("日本語"), 6)
        self.assertEqual(display_width("a日b"), 4)

    def test_fullwidth_and_halfwidth(self):
        self.assertEqual(display_width("Ａ"), 2)
        self.assertEqual(display_width("ｱ"), 1)

    def test_combining_and_zero_width(self):
        self.assertEqual(display_width("é"), 1)
        self.assertEqual(display_width("a​b"), 2)
        self.assertEqual(display_width("a‍b"), 2)

    def test_emoji(self):
        self.assertEqual(display_width("\U0001F600"), 2)

    def test_mixed(self):
        self.assertEqual(display_width(BOLD + "日本" + R + " ok"), 7)

    def test_strip_unchanged(self):
        self.assertEqual(strip_ansi(BOLD + "x" + R), "x")


class WrapPlain(unittest.TestCase):
    def test_width_uses_display_columns(self):
        self.assertEqual(wrap("日本 語彙 辞書", 5), ["日本", "語彙", "辞書"])
        self.assertEqual(wrap("日本 語", 7), ["日本 語"])

    def test_combining_does_not_count(self):
        self.assertEqual(wrap("éé ab", 5), ["éé ab"])

    def test_long_word_split(self):
        self.assertEqual(wrap("abcdefghij", 4), ["abcd", "efgh", "ij"])

    def test_long_word_starts_new_line(self):
        self.assertEqual(wrap("hi abcdefg", 4), ["hi", "abcd", "efg"])

    def test_last_chunk_continues(self):
        self.assertEqual(wrap("abcdef g", 4), ["abcd", "ef g"])
        self.assertEqual(wrap("xy abcdef g h", 4), ["xy", "abcd", "ef g", "h"])

    def test_long_word_exact_multiple(self):
        self.assertEqual(wrap("abcdefgh", 4), ["abcd", "efgh"])

    def test_wide_chars_not_split(self):
        self.assertEqual(wrap("日本語", 5), ["日本", "語"])
        self.assertEqual(wrap("a日本語", 4), ["a日", "本語"])
        self.assertEqual(wrap("abc日", 4), ["abc", "日"])

    def test_width_one_wide_char_alone(self):
        self.assertEqual(wrap("日a本", 1), ["日", "a", "本"])

    def test_combining_stays_with_base_at_break(self):
        self.assertEqual(wrap("abécd", 3), ["abé", "cd"])
        self.assertEqual(wrap("日́本", 2), ["日́", "本"])

    def test_paragraphs_and_blank(self):
        self.assertEqual(wrap("one\n\n   \ntwo three", 7), ["one", "", "", "two", "three"])

    def test_unchanged_behaviour(self):
        self.assertEqual(wrap("the quick brown fox", 10), ["the quick", "brown fox"])
        self.assertEqual(wrap("", 3), [""])
        with self.assertRaises(ValueError):
            wrap("a", 0)


class WrapAnsi(unittest.TestCase):
    def test_codes_do_not_count(self):
        text = RED + "red" + R + " " + BOLD + "bold" + R
        self.assertEqual(wrap(text, 8), [text])

    def test_wrap_between_words_keeps_closed_styles(self):
        text = RED + "aaa" + R + " " + BOLD + "bbb" + R
        self.assertEqual(wrap(text, 4), [RED + "aaa" + R, BOLD + "bbb" + R])

    def test_style_spanning_words_is_carried(self):
        text = RED + "aa bb" + R
        self.assertEqual(wrap(text, 3), [RED + "aa" + R, RED + "bb" + R])

    def test_style_carry_multiple_open(self):
        text = BOLD + "x " + RED + "yy zz" + R
        self.assertEqual(
            wrap(text, 4),
            [BOLD + "x " + RED + "yy" + R, BOLD + RED + "zz" + R],
        )

    def test_unclosed_style_closed_at_end(self):
        self.assertEqual(wrap(RED + "abc", 10), [RED + "abc" + R])

    def test_long_word_with_codes(self):
        text = RED + "abcdef" + R
        self.assertEqual(wrap(text, 4), [RED + "abcd" + R, RED + "ef" + R])

    def test_break_sequence_stays_on_previous_line(self):
        text = "abcd" + RED + "efgh" + R
        self.assertEqual(wrap(text, 4), ["abcd" + RED + R, RED + "efgh" + R])

    def test_reset_variants_clear(self):
        text = BOLD + "ab" + "\x1b[m" + "cd efgh"
        self.assertEqual(wrap(text, 5), [BOLD + "ab" + "\x1b[m" + "cd", "efgh"])

    def test_carry_across_paragraphs_blank_stays_empty(self):
        text = RED + "one\n\ntwo" + R
        self.assertEqual(wrap(text, 9), [RED + "one" + R, "", RED + "two" + R])

    def test_wide_and_ansi_together(self):
        text = RED + "日本語" + R
        self.assertEqual(wrap(text, 4), [RED + "日本" + R, RED + "語" + R])


class Table(unittest.TestCase):
    def test_cjk_alignment(self):
        out = render_table([["名前", "x"], ["ab", "y"]], [6, 1])
        self.assertEqual(out, "名前   | x\nab     | y")

    def test_ansi_cells_padded_by_visible_width(self):
        out = render_table([[RED + "ab" + R, "z"]], [4, 1])
        self.assertEqual(out, RED + "ab" + R + "   | z")

    def test_right_and_centre(self):
        out = render_table([["日", "ab", "c"]], [4, 5, 4], "rcl")
        self.assertEqual(out, "  日 |  ab   | c")

    def test_centre_odd_gap(self):
        self.assertEqual(render_table([["a", "b"]], [4, 1], "c"), " a   | b")

    def test_wrapped_cell_with_wide_chars(self):
        out = render_table([["日本語 ab", "q"]], [4, 1])
        self.assertEqual(out, "日本 | q\n語   |\nab   |")

    def test_multiline_ansi_cell_each_line_closed(self):
        out = render_table([[RED + "aa bb" + R, "k"]], [2, 1])
        self.assertEqual(out, RED + "aa" + R + " | k\n" + RED + "bb" + R + " |")

    def test_short_row_and_trailing_spaces(self):
        out = render_table([["a"], ["b", "c"]], [3, 3])
        self.assertEqual(out, "a   |\nb   | c")

    def test_too_many_cells(self):
        with self.assertRaises(ValueError):
            render_table([["a", "b"]], [3])

    def test_empty_cell_lines(self):
        self.assertEqual(render_table([["", "x"]], [2, 1]), "   | x")


class Truncate(unittest.TestCase):
    def test_unchanged_when_fits_by_display_width(self):
        self.assertEqual(truncate("日本語", 6), "日本語")
        self.assertEqual(truncate(RED + "abc" + R, 3), RED + "abc" + R)

    def test_cjk_cut(self):
        self.assertEqual(truncate("日本語日本語", 9), "日本語...")
        self.assertEqual(truncate("日本語日本語", 8), "日本...")

    def test_never_splits_wide(self):
        self.assertEqual(truncate("a日本語", 6, "~"), "a日本~")
        self.assertEqual(truncate("ab日本語", 5, "~"), "ab日~")

    def test_ansi_not_counted_and_closed(self):
        text = RED + "abcdefgh" + R
        self.assertEqual(truncate(text, 6), RED + "abc" + R + "...")

    def test_ansi_before_cut_kept(self):
        text = "ab" + RED + "cd" + R + "efgh"
        self.assertEqual(truncate(text, 6), "ab" + RED + "c" + R + "...")
        text2 = "abc" + RED + "defghi" + R
        self.assertEqual(truncate(text2, 6), "abc" + RED + R + "...")

    def test_closed_style_not_reset_again(self):
        text = RED + "ab" + R + "cdefghij"
        self.assertEqual(truncate(text, 6), RED + "ab" + R + "c...")

    def test_combining_kept_with_base(self):
        self.assertEqual(truncate("abécdefg", 6), "abé...")

    def test_placeholder_wide(self):
        self.assertEqual(truncate("abcdefgh", 5, "…"), "abcd…")
        self.assertEqual(truncate("abcdefgh", 5, "。"), "abc。")

    def test_placeholder_too_wide(self):
        with self.assertRaises(ValueError):
            truncate("abcdefgh", 2)
        self.assertEqual(truncate("abc", 3, "..."), "abc")

    def test_zero_width_budget(self):
        self.assertEqual(truncate("abcdef", 3), "...")


if __name__ == "__main__":
    unittest.main()
