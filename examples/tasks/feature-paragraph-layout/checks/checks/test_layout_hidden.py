import itertools
import random
import re
import sys
import time
import unittest

from layout import format_paragraph, format_text, justify_words, wrap, align_line


# ---------------------------------------------------------------- oracle

def tokenize(text):
    """pieces and whether a space precedes each piece (first piece of a word: True)."""
    pieces, spaces = [], []
    for word in text.split():
        cuts = [m.end() for m in re.finditer(r"(?<=[A-Za-z0-9])-(?=[A-Za-z0-9])", word)]
        # str.isalnum is Unicode-aware; words in the tests are ASCII so the regex is equivalent
        bounds = [0] + cuts + [len(word)]
        for k in range(len(bounds) - 1):
            pieces.append(word[bounds[k]:bounds[k + 1]])
            spaces.append(k == 0)
    return pieces, spaces


def natural(pieces, spaces, a, b):
    return sum(len(p) for p in pieces[a:b]) + sum(1 for k in range(a + 1, b) if spaces[k])


def line_cost(pieces, spaces, a, b, avail, last):
    if last:
        return 0
    n = natural(pieces, spaces, a, b)
    if n > avail:
        return 0
    return (avail - n) ** 2


def feasible(pieces, spaces, a, b, avail):
    return b - a == 1 or natural(pieces, spaces, a, b) <= avail


def brute(pieces, spaces, a1, a2):
    n = len(pieces)
    best = None
    for mask in range(1 << max(0, n - 1)):
        cuts = [0] + [k + 1 for k in range(n - 1) if mask >> k & 1] + [n]
        ranges = list(zip(cuts, cuts[1:]))
        cost, ok = 0, True
        for i, (a, b) in enumerate(ranges):
            avail = a1 if i == 0 else a2
            if not feasible(pieces, spaces, a, b, avail):
                ok = False
                break
            cost += line_cost(pieces, spaces, a, b, avail, i == len(ranges) - 1)
        if not ok:
            continue
        key = (cost, tuple(-(b - a) for a, b in ranges))
        if best is None or key < best[0]:
            best = (key, ranges)
    return best[1] if best else []


def recursive_best(pieces, spaces, a1, a2):
    n = len(pieces)
    memo = {}

    def solve(i):
        if i == n:
            return 0, ()
        if i in memo:
            return memo[i]
        avail = a1 if i == 0 else a2
        best = None
        for j in range(i + 1, n + 1):
            if not feasible(pieces, spaces, i, j, avail):
                break
            c, rest = solve(j)
            key = (c + line_cost(pieces, spaces, i, j, avail, j == n), (-(j - i),) + rest)
            if best is None or key < best:
                best = key
        memo[i] = best
        return best

    sys.setrecursionlimit(10000)
    _, lens = solve(0)
    ranges, i = [], 0
    for l in lens:
        ranges.append((i, i - l))
        i -= l
    return ranges


def render(pieces, spaces, ranges, a1, a2, i1, i2, align):
    out = []
    for n, (a, b) in enumerate(ranges):
        avail = a1 if n == 0 else a2
        pad = i1 if n == 0 else i2
        last = n == len(ranges) - 1
        seg = pieces[a:b]
        sp = [spaces[k] for k in range(a + 1, b)]
        text = seg[0] + "".join((" " if s else "") + p for s, p in zip(sp, seg[1:]))
        if align == "justify" and not last and any(sp):
            extra = avail - len(text)
            gaps = sum(sp)
            if extra > 0:
                base, rem = divmod(extra, gaps)
                parts, g = [seg[0]], 0
                for s, p in zip(sp, seg[1:]):
                    if s:
                        parts.append(" " * (1 + base + (1 if g < rem else 0)))
                        g += 1
                    parts.append(p)
                text = "".join(parts)
        elif align == "right":
            text = " " * max(0, avail - len(text)) + text
        elif align == "center":
            text = " " * (max(0, avail - len(text)) // 2) + text
        out.append(" " * pad + text)
    return out


def rand_word(rng, hyphen_prob):
    n = rng.randrange(1, 9)
    chars = []
    for k in range(n):
        if k and k < n - 1 and rng.random() < hyphen_prob:
            chars.append("-")
        else:
            chars.append(rng.choice("abcdefgh0123"))
    if rng.random() < 0.05:
        chars.append("-")
    return "".join(chars)


class Optimal(unittest.TestCase):
    def opt(self, text, width, **kw):
        return format_paragraph(text, width, method="optimal", **kw)

    def test_beats_greedy(self):
        self.assertEqual(format_paragraph("aaa bb cc ddddd", 6), ["aaa bb", "cc", "ddddd"])
        self.assertEqual(self.opt("aaa bb cc ddddd", 6), ["aaa", "bb cc", "ddddd"])

    def test_classic_paragraph(self):
        text = "the quick brown fox jumps over the lazy dog and keeps running far away"
        self.assertEqual(self.opt(text, 20), ["the quick brown", "fox jumps over the", "lazy dog and keeps", "running far away"])
        self.assertEqual(self.opt(text, 30), ["the quick brown fox jumps over", "the lazy dog and keeps running", "far away"])

    def test_trivial_inputs(self):
        self.assertEqual(self.opt("", 10), [])
        self.assertEqual(self.opt("  \n\t ", 10), [])
        self.assertEqual(self.opt("word", 10), ["word"])
        self.assertEqual(self.opt("word", 2), ["word"])
        self.assertEqual(self.opt("a b", 3), ["a b"])
        self.assertEqual(self.opt("a b", 2), ["a", "b"])

    def test_overfull_words(self):
        self.assertEqual(self.opt("a abcdefghij b c", 4), ["a", "abcdefghij", "b c"])
        self.assertEqual(self.opt("abcdefghij klmnopqrstu", 4), ["abcdefghij", "klmnopqrstu"])

    def test_hyphen_break_points(self):
        self.assertEqual(self.opt("state-of-the-art design", 10), ["state-of-", "the-art", "design"])
        self.assertEqual(self.opt("a-b c-d", 3), ["a-b", "c-d"])
        self.assertEqual(self.opt("aa-bb-cc", 5), ["aa-", "bb-cc"])
        self.assertEqual(self.opt("aaa--bbb", 4), ["aaa--bbb"])
        self.assertEqual(self.opt("-aaa- ccc", 4), ["-aaa-", "ccc"])
        self.assertEqual(self.opt("well-known e-mail", 8), ["well-", "known e-", "mail"])
        for text in ["a- b", "-a", "a--b", "a-", "3-4", "x-y-z", "e-mail", "well-known-fact"]:
            self.assertEqual(self.opt(text, 40), [text])
        # a hyphen next to a non-alphanumeric character is not a break point
        self.assertEqual(self.opt("ab-.cd ef-gh", 6), ["ab-.cd", "ef-gh"])
        self.assertEqual(self.opt("ab.-cd e", 4), ["ab.-cd", "e"])

    def test_greedy_never_splits_hyphenated_words(self):
        self.assertEqual(format_paragraph("state-of-the-art design", 10), ["state-of-the-art", "design"])
        self.assertEqual(format_paragraph("a-b", 2), ["a-b"])

    def test_tie_break_prefers_long_early_lines(self):
        # "a a a a" at width 3: [a a][a a] and [a a a?]... only 2 per line fits; check a real tie
        self.assertEqual(self.opt("a b c d", 7), ["a b c d"])
        self.assertEqual(self.opt("aa bb cc dd", 8), ["aa bb cc", "dd"])
        # equal-cost layouts (2,1,1,1) and (1,2,1,1): the one with the longer first line wins
        self.assertEqual(self.opt("xx x xx xxxx xx", 6), ["xx x", "xx", "xxxx", "xx"])
        self.assertEqual(self.opt("xx xx xx xxxx xxxx", 5), ["xx xx", "xx", "xxxx", "xxxx"])
        self.assertEqual(self.opt("xxxx xx xxxx xxxx xx", 7), ["xxxx xx", "xxxx", "xxxx xx"])

    def test_first_indent(self):
        self.assertEqual(self.opt("aaa bb cc ddddd", 8, first_indent=2, indent=0)[0][:2], "  ")
        got = self.opt("one two three four five six", 12, first_indent=4)
        self.assertTrue(all(len(l) <= 12 for l in got))
        self.assertTrue(got[0].startswith("    one"))

    def test_indent_applies_to_later_lines(self):
        got = self.opt("one two three four five six seven", 14, indent=3)
        self.assertTrue(all(l.startswith("   ") and len(l) <= 14 for l in got))
        got = format_paragraph("one two three four five six seven", 14, indent=3, first_indent=0)
        self.assertTrue(got[0][0] != " " and all(l.startswith("   ") for l in got[1:]))

    def test_errors(self):
        for kw in [dict(width=0), dict(width=5, indent=5), dict(width=5, first_indent=5), dict(width=5, first_indent=-1),
                   dict(width=5, method="knuth"), dict(width=5, align="zigzag"), dict(width=-3)]:
            with self.subTest(kw=kw):
                with self.assertRaises(ValueError):
                    format_paragraph("a b c", **kw)
        with self.assertRaises(ValueError):
            format_paragraph("a b c", 5, method="optimal", align="zigzag")

    def test_alignments_on_optimal_breaks(self):
        text = "the quick brown fox jumps over the lazy dog and keeps running far away"
        j = self.opt(text, 20, align="justify")
        self.assertEqual([len(l) for l in j[:-1]], [20] * (len(j) - 1))
        self.assertEqual(j[-1], "running far away")
        r = self.opt(text, 20, align="right")
        self.assertTrue(all(len(l) == 20 or l is r[-1] for l in r[:-1]) and r[-1].endswith("away"))
        c = self.opt("aa bb cc dd", 9, align="center")
        self.assertEqual(c, render(*tokenize("aa bb cc dd"), brute(*tokenize("aa bb cc dd"), 9, 9), 9, 9, 0, 0, "center"))

    def test_justify_gap_distribution(self):
        # 3 gaps, 5 extra spaces: base 1, remainder 2 -> leftmost two gaps get one more
        self.assertEqual(justify_words(["a", "b", "c", "d"], 12), "a   b   c  d")
        self.assertEqual(align_line(["aa", "b", "c"], 11, "justify"), "aa    b   c")
        self.assertEqual(self.opt("aa b c ddddddddddd", 11, align="justify")[0], "aa    b   c")

    def test_justify_with_hyphen_joins(self):
        # joins are not stretchable; only the space gap grows
        got = self.opt("ab-cd ef", 9, align="justify")
        self.assertEqual(got, ["ab-cd ef"])
        got = self.opt("ab-cd ef gh ij", 9, align="justify")
        self.assertEqual(got, ["ab-cd  ef", "gh ij"])
        self.assertEqual(self.opt("ab-cd ef gh ij", 9, align="justify"), render(*tokenize("ab-cd ef gh ij"), brute(*tokenize("ab-cd ef gh ij"), 9, 9), 9, 9, 0, 0, "justify"))

    def test_single_piece_lines_are_not_padded(self):
        self.assertEqual(self.opt("abcdefghij kl", 4, align="justify"), ["abcdefghij", "kl"])
        self.assertEqual(self.opt("abcdefghij kl", 4, align="right"), ["abcdefghij", "  kl"])


class Differential(unittest.TestCase):
    def check(self, rng, count, align, hyphen_prob, max_words, widths):
        for _ in range(count):
            text = " ".join(rand_word(rng, hyphen_prob) for _ in range(rng.randrange(1, max_words + 1)))
            width = rng.randrange(*widths)
            i2 = rng.randrange(0, min(4, width))
            i1 = rng.choice([None, rng.randrange(0, min(5, width))])
            pieces, spaces = tokenize(text)
            if len(pieces) > 12:
                continue
            a1 = width - (i2 if i1 is None else i1)
            a2 = width - i2
            want = render(pieces, spaces, brute(pieces, spaces, a1, a2), a1, a2, i2 if i1 is None else i1, i2, align)
            got = format_paragraph(text, width, align=align, indent=i2, first_indent=i1, method="optimal")
            self.assertEqual(got, want, (text, width, i1, i2, align))

    def test_left_no_hyphens(self):
        self.check(random.Random(1), 1000, "left", 0.0, 8, (4, 18))

    def test_left_with_hyphens(self):
        self.check(random.Random(2), 1000, "left", 0.35, 6, (4, 16))

    def test_justify(self):
        self.check(random.Random(3), 1000, "justify", 0.2, 7, (5, 20))

    def test_right(self):
        self.check(random.Random(4), 800, "right", 0.2, 7, (5, 20))

    def test_center(self):
        self.check(random.Random(5), 800, "center", 0.2, 7, (5, 20))

    def test_wide_and_narrow(self):
        self.check(random.Random(6), 500, "left", 0.2, 9, (1, 6))
        self.check(random.Random(7), 500, "justify", 0.2, 9, (20, 40))

    def test_mid_size_against_exhaustive_recursion(self):
        rng = random.Random(8)
        for _ in range(60):
            text = " ".join(rand_word(rng, 0.25) for _ in range(rng.randrange(60, 120)))
            width = rng.randrange(8, 30)
            i2 = rng.randrange(0, 4)
            i1 = rng.randrange(0, 6)
            pieces, spaces = tokenize(text)
            a1, a2 = width - i1, width - i2
            want = render(pieces, spaces, recursive_best(pieces, spaces, a1, a2), a1, a2, i1, i2, "justify")
            got = format_paragraph(text, width, align="justify", indent=i2, first_indent=i1, method="optimal")
            self.assertEqual(got, want)

    def test_greedy_unchanged_and_first_indent(self):
        rng = random.Random(9)
        for _ in range(500):
            words = [rand_word(rng, 0.0) for _ in range(rng.randrange(0, 12))]
            width = rng.randrange(3, 20)
            text = "  ".join(words)
            got = format_paragraph(text, width)
            self.assertEqual(got, [" ".join(l) for l in wrap(words, width)])
            i1 = rng.randrange(0, min(5, width))
            i2 = rng.randrange(0, min(5, width))
            g2 = format_paragraph(text, width, indent=i2, first_indent=i1)
            # greedy with a different first width
            exp, i, n = [], 0, len(words)
            while i < n:
                avail = width - (i1 if i == 0 else i2)
                j, ln = i + 1, len(words[i])
                while j < n and ln + 1 + len(words[j]) <= avail:
                    ln += 1 + len(words[j])
                    j += 1
                exp.append(" " * (i1 if i == 0 else i2) + " ".join(words[i:j]))
                i = j
            self.assertEqual(g2, exp)


def _more_layout_seeds():
    def mk(seed, align, hp, widths):
        def t(self):
            self.check(random.Random(seed), 90, align, hp, 8, widths)
        return t

    n = 0
    for align in ("left", "justify", "right", "center"):
        for hp, widths in ((0.0, (3, 14)), (0.3, (6, 26)), (0.15, (10, 40)), (0.5, (4, 12)), (0.1, (2, 9))):
            n += 1
            setattr(Differential, "test_seed_%02d_%s" % (n, align), mk(1000 + n, align, hp, widths))


_more_layout_seeds()


class Performance(unittest.TestCase):
    def cost_of(self, lines, avail_first, avail_rest, pad_first, pad_rest):
        total = 0
        for n, l in enumerate(lines[:-1]):
            avail = avail_first if n == 0 else avail_rest
            body = l[pad_first if n == 0 else pad_rest:]
            if len(body) <= avail:
                total += (avail - len(body)) ** 2
        return total

    def test_long_paragraph(self):
        rng = random.Random(10)
        words = ["".join(rng.choice("abcdefgh") for _ in range(rng.randrange(1, 10))) for _ in range(40000)]
        text = " ".join(words)
        t = time.perf_counter()
        lines = format_paragraph(text, 72, method="optimal")
        self.assertLess(time.perf_counter() - t, 6.0)
        self.assertEqual(" ".join(lines).split(), words)
        self.assertTrue(all(len(l) <= 72 for l in lines))
        # not worse than greedy
        greedy = format_paragraph(text, 72)
        self.assertLessEqual(self.cost_of(lines, 72, 72, 0, 0), self.cost_of(greedy, 72, 72, 0, 0))
        self.assertLess(len(lines), len(greedy) + 3)

    def test_long_paragraph_optimal_cost_matches_simple_dp(self):
        rng = random.Random(11)
        words = ["".join(rng.choice("abcdefgh") for _ in range(rng.randrange(1, 12))) for _ in range(6000)]
        lens = [len(w) for w in words]
        n, W = len(words), 60
        best = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            b, ln = None, -1
            for j in range(i, n):
                ln += lens[j] + 1
                if ln > W:
                    break
                c = 0 if j == n - 1 else (W - ln) ** 2
                if b is None or c + best[j + 1] < b:
                    b = c + best[j + 1]
            best[i] = b
        lines = format_paragraph(" ".join(words), W, method="optimal")
        self.assertEqual(self.cost_of(lines, W, W, 0, 0), best[0])

    def test_many_overfull_words_and_text(self):
        t = time.perf_counter()
        lines = format_paragraph(" ".join(["x" * 100] * 3000), 40, method="optimal")
        self.assertEqual(len(lines), 3000)
        text = "\n\n".join(" ".join("w%d" % i for i in range(200)) for _ in range(100))
        out = format_text(text, 50, method="optimal", align="justify")
        self.assertEqual(len(out.split("\n\n")), 100)
        self.assertLess(time.perf_counter() - t, 6.0)


class TextAndRegression(unittest.TestCase):
    def test_format_text_passes_options(self):
        text = "aaa bb cc ddddd\n\n\n  \nxx yy"
        self.assertEqual(format_text(text, 6, method="optimal"), "aaa\nbb cc\nddddd\n\nxx yy")
        self.assertEqual(format_text(text, 6), "aaa bb\ncc\nddddd\n\nxx yy")
        self.assertEqual(format_text("a b c d", 4, indent=1, first_indent=0, method="optimal"), "a b\n c d")
        self.assertEqual(format_text("", 5, method="optimal"), "")

    def test_old_behaviour(self):
        text = "the quick brown fox jumps over the lazy dog and keeps running far away"
        self.assertEqual(format_paragraph(text, 20), ["the quick brown fox", "jumps over the lazy", "dog and keeps", "running far away"])
        self.assertEqual(format_paragraph("aa bb cc", 5), ["aa bb", "cc"])
        self.assertEqual(format_paragraph("   ", 5), [])
        self.assertEqual(justify_words(["a", "b", "c"], 8), "a   b  c")
        self.assertEqual(format_paragraph("aa bb cc dd", 7, "justify"), ["aa   bb", "cc dd"])
        self.assertEqual(format_paragraph("aa bb cc", 5, "right"), ["aa bb", "   cc"])
        self.assertEqual(format_paragraph("aa bb cc", 7, "center"), [" aa bb", "  cc"])
        self.assertEqual(format_paragraph("aa bb cc", 7, indent=2), ["  aa bb", "  cc"])
        self.assertEqual(wrap("aaa bb c dddd".split(), 6), [["aaa", "bb"], ["c", "dddd"]])
        self.assertEqual(wrap(["abcdefghij", "k"], 4), [["abcdefghij"], ["k"]])
        self.assertEqual(format_text("aa bb\n\n\n  \ncc dd ee", 5), "aa bb\n\ncc dd\nee")

    def test_default_method_is_greedy(self):
        self.assertEqual(format_paragraph("aaa bb cc ddddd", 6), format_paragraph("aaa bb cc ddddd", 6, method="greedy"))


if __name__ == "__main__":
    unittest.main()
