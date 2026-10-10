import random
import sys
import time
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from md_examples import EXAMPLES  # noqa: E402

from mdinline import outline, plain_text, render_document, render_inline  # noqa: E402

ASCII_P = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


# ---------------------------------------------------------------- reference implementation

def r_ws(c):
    return c in "\t\n\f\r" or unicodedata.category(c) == "Zs"


def r_punct(c):
    return c in ASCII_P or unicodedata.category(c)[0] in ("P", "S")


def r_esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


class D:
    def __init__(self, ch, n, o, c):
        self.ch, self.n, self.orig, self.open, self.close = ch, n, n, o, c


def r_scan(s):
    items = []
    text = []

    def flush():
        if text:
            items.append(("t", "".join(text)))
            text.clear()

    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in ASCII_P:
            text.append(s[i + 1])
            i += 2
            continue
        if c == "`":
            j = i
            while j < len(s) and s[j] == "`":
                j += 1
            run = j - i
            # find the next run of exactly this many backticks
            k, close = j, None
            while k < len(s):
                if s[k] == "`":
                    m = k
                    while m < len(s) and s[m] == "`":
                        m += 1
                    if m - k == run:
                        close = k
                        break
                    k = m
                else:
                    k += 1
            if close is None:
                text.append("`" * run)
                i = j
            else:
                raw = s[j:close].replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                if len(raw) >= 2 and raw[0] == " " and raw[-1] == " " and raw != " " * len(raw):
                    raw = raw[1:-1]
                flush()
                items.append(("c", raw))
                i = close + run
            continue
        if c in "*_":
            j = i
            while j < len(s) and s[j] == c:
                j += 1
            before = s[i - 1] if i else " "
            after = s[j] if j < len(s) else " "
            left = (not r_ws(after)) and ((not r_punct(after)) or r_ws(before) or r_punct(before))
            right = (not r_ws(before)) and ((not r_punct(before)) or r_ws(after) or r_punct(after))
            if c == "*":
                o, cl = left, right
            else:
                o = left and ((not right) or r_punct(before))
                cl = right and ((not left) or r_punct(after))
            flush()
            items.append(("d", D(c, j - i, o, cl)))
            i = j
            continue
        text.append(c)
        i += 1
    flush()
    return items


def r_tree(s):
    items = r_scan(s)
    i = 0
    while i < len(items):
        it = items[i]
        if it[0] == "d" and it[1].close and it[1].n > 0:
            cl = it[1]
            found = None
            j = i - 1
            while j >= 0:
                o = items[j]
                if o[0] == "d" and o[1].n > 0 and o[1].ch == cl.ch and o[1].open:
                    od = o[1]
                    odd = (cl.open or od.close) and cl.orig % 3 != 0 and (od.orig + cl.orig) % 3 == 0
                    if not odd:
                        found = j
                        break
                j -= 1
            if found is None:
                i += 1
                continue
            od = items[found][1]
            use = 2 if (cl.n >= 2 and od.n >= 2) else 1
            od.n -= use
            cl.n -= use
            box = ("strong" if use == 2 else "em", items[found + 1:i])
            items[found + 1:i] = [("b", box)]
            i = found + 2
            if cl.n == 0:
                i += 1
            continue
        i += 1
    return items


def r_render(items, mode):
    out = []
    for it in items:
        if it[0] == "t":
            out.append(r_esc(it[1]) if mode == "html" else it[1])
        elif it[0] == "c":
            out.append("<code>%s</code>" % r_esc(it[1]) if mode == "html" else it[1])
        elif it[0] == "d":
            ch = it[1].ch * it[1].n
            out.append(r_esc(ch) if mode == "html" else ch)
        else:
            tag, kids = it[1]
            inner = r_render(kids, mode)
            out.append("<%s>%s</%s>" % (tag, inner, tag) if mode == "html" else inner)
    return "".join(out)


def ref_html(s):
    return r_render(r_tree(s), "html")


def ref_plain(s):
    return r_render(r_tree(s), "plain")


# ---------------------------------------------------------------- tests

class SpecExamples(unittest.TestCase):
    def test_reference_agrees_with_the_spec_examples(self):
        # guards the oracle itself
        for src, want in EXAMPLES:
            self.assertEqual(ref_html(src), want, src)


def _add_example_tests():
    def mk(chunk):
        def t(self):
            for src, want in chunk:
                with self.subTest(src=src):
                    self.assertEqual(render_inline(src), want)
        return t

    for n in range(0, len(EXAMPLES), 4):
        setattr(SpecExamples, "test_examples_%03d" % n, mk(EXAMPLES[n:n + 4]))


_add_example_tests()


class Interactions(unittest.TestCase):
    def test_unicode_punctuation_and_whitespace(self):
        cases = [
            ("*\u20ac*a", "*\u20ac*a"),                 # euro sign is a symbol: punctuation since 0.31
            ("a*\u20ac*", "a*\u20ac*"),
            ("*\u00a0a*", "*\u00a0a*"),                 # no-break space is whitespace
            ("*a\u00a0*", "*a\u00a0*"),
            ("*\u3000a*", "*\u3000a*"),
            ("a*\u2014b*", "a*\u2014b*"),
            ("*\u2014b*", "<em>\u2014b</em>"),
            ("a *\u2014b*", "a <em>\u2014b</em>"),
            ("*a*\u00bb", "<em>a</em>\u00bb"),
            ("\u00ab*a*", "\u00ab<em>a</em>"),
            ("_\u00a9_a", "_\u00a9_a"),
            ("a_\u00a9_", "a_\u00a9_"),
            ("_\u00a9_", "<em>\u00a9</em>"),
            ("(*\u00a9*)", "(<em>\u00a9</em>)"),
            ("\u4f60*\u597d*", "\u4f60<em>\u597d</em>"),
            ("\u4f60_\u597d_", "\u4f60_\u597d_"),
            ("*\u3002a*", "<em>\u3002a</em>"),
            ("x*\u3002a*", "x*\u3002a*"),
            ("*a*\u00a1", "<em>a</em>\u00a1"),
        ]
        for src, want in cases:
            with self.subTest(src=src):
                self.assertEqual(render_inline(src), want)
                self.assertEqual(ref_html(src), want)

    def test_other_whitespace_forms(self):
        self.assertEqual(render_inline("*a\t*"), "*a\t*")
        self.assertEqual(render_inline("*\ta*"), "*\ta*")
        self.assertEqual(render_inline("*a\r*"), "*a\r*")
        self.assertEqual(render_inline("*a\f*"), "*a\f*")
        self.assertEqual(render_inline("*a\u000b*"), ref_html("*a\u000b*"))

    def test_code_spans_take_precedence(self):
        self.assertEqual(render_inline("*a `b*` c*"), "<em>a <code>b*</code> c</em>")
        self.assertEqual(render_inline("`*a*`"), "<code>*a*</code>")
        self.assertEqual(render_inline("*`a`*"), "<em><code>a</code></em>")
        self.assertEqual(render_inline("**`a`**"), "<strong><code>a</code></strong>")
        self.assertEqual(render_inline("`a`*b*`c`"), "<code>a</code><em>b</em><code>c</code>")
        self.assertEqual(render_inline("*foo`*`"), "*foo<code>*</code>")
        self.assertEqual(render_inline("`code`_a_"), "<code>code</code><em>a</em>")
        self.assertEqual(render_inline("a`b`_c_"), ref_html("a`b`_c_"))
        self.assertEqual(render_inline("_`b`_"), "<em><code>b</code></em>")

    def test_flanking_looks_at_the_source_not_the_node_kind(self):
        # the backtick before/after a run counts as punctuation
        self.assertEqual(render_inline("`a`*b*"), "<code>a</code><em>b</em>")
        self.assertEqual(render_inline("*b*`a`"), "<em>b</em><code>a</code>")
        self.assertEqual(render_inline("_`a`_b"), ref_html("_`a`_b"))
        self.assertEqual(render_inline("x_`a`_"), ref_html("x_`a`_"))
        # an escaped character before a run is punctuation for flanking purposes
        self.assertEqual(render_inline("\\**a*"), ref_html("\\**a*"))
        self.assertEqual(render_inline("a\\**b*"), ref_html("a\\**b*"))
        self.assertEqual(render_inline("a\\_b_"), ref_html("a\\_b_"))

    def test_escapes(self):
        self.assertEqual(render_inline("\\*a\\*"), "*a*")
        self.assertEqual(render_inline("*a\\*"), "*a*")
        self.assertEqual(render_inline("\\**a*"), ref_html("\\**a*"))
        self.assertEqual(render_inline("*a*\\*"), "<em>a</em>*")
        self.assertEqual(render_inline("*\\_a_*"), ref_html("*\\_a_*"))
        self.assertEqual(render_inline("**a\\*\\***"), "<strong>a**</strong>")
        self.assertEqual(render_inline("a \\\\*b*"), "a \\<em>b</em>")
        self.assertEqual(render_inline("\\a*b*"), "\\a<em>b</em>")

    def test_html_escaping_inside_emphasis(self):
        self.assertEqual(render_inline("*a < b & c > d \"q\"*"), "<em>a &lt; b &amp; c &gt; d &quot;q&quot;</em>")
        self.assertEqual(render_inline("**<b>**"), "<strong>&lt;b&gt;</strong>")

    def test_newlines(self):
        self.assertEqual(render_inline("*a\nb*"), "<em>a\nb</em>")
        self.assertEqual(render_inline("a*\nb*"), "a*\nb*")
        self.assertEqual(render_inline("*a\n*b"), "*a\n*b")
        self.assertEqual(render_inline("_a_\n_b_"), "<em>a</em>\n<em>b</em>")

    def test_rule_of_three(self):
        cases = ["*foo**bar*", "**foo*bar**", "***a**b*", "*a***b**", "**a***b*", "a***b***c", "***a*b**c", "*a**b***",
                 "_a__b___", "__a_b__", "*a**b**c*", "**a*b*c**", "a*b**c", "*a*b**c**", "***a** b*", "*a **b***c"]
        for src in cases:
            with self.subTest(src=src):
                self.assertEqual(render_inline(src), ref_html(src))

    def test_intraword_underscore_vs_star(self):
        for src in ["snake_case_name", "snake_case_name_", "_snake_case", "2*3*4", "2_3_4", "a*b*c", "a_b_c",
                    "__init__.py", "**kwargs", "*args, **kwargs", "foo_bar_ baz", "x_ y_z _w"]:
            with self.subTest(src=src):
                self.assertEqual(render_inline(src), ref_html(src))
        self.assertEqual(render_inline("snake_case_name"), "snake_case_name")
        self.assertEqual(render_inline("__init__.py"), "<strong>init</strong>.py")
        self.assertEqual(render_inline("2*3*4"), "2<em>3</em>4")

    def test_unmatched_delimiters_stay_literal_and_escaped(self):
        self.assertEqual(render_inline("*"), "*")
        self.assertEqual(render_inline("**"), "**")
        self.assertEqual(render_inline("a*"), "a*")
        self.assertEqual(render_inline("*a"), "*a")
        self.assertEqual(render_inline(""), "")
        self.assertEqual(render_inline("_ _"), "_ _")
        self.assertEqual(render_inline("*<*"), ref_html("*<*"))

    def test_plain_text(self):
        self.assertEqual(plain_text("*a* **b** _c_ `d*` \\*e"), "a b c d* *e")
        self.assertEqual(plain_text("*foo **bar *baz* bim** bop*"), "foo bar baz bim bop")
        self.assertEqual(plain_text("**foo*"), "*foo")
        self.assertEqual(plain_text("a * b _ c"), "a * b _ c")
        self.assertEqual(plain_text("snake_case_name"), "snake_case_name")
        self.assertEqual(plain_text("a < b & c"), "a < b & c")

    def test_document_and_outline(self):
        md = "# The *big* title\n\nfirst *line*\n second **line**\n\n## Sub `code` and _x_\ntext\n###### six"
        self.assertEqual(
            render_document(md),
            "<h1>The <em>big</em> title</h1>\n<p>first <em>line</em>\nsecond <strong>line</strong></p>\n"
            "<h2>Sub <code>code</code> and <em>x</em></h2>\n<p>text</p>\n<h6>six</h6>")
        self.assertEqual(outline(md), [(1, "The big title"), (2, "Sub code and x"), (6, "six")])
        self.assertEqual(outline("#   a_b_c  \n#\n# **bold**"), [(1, "a_b_c"), (1, "bold")])

    def test_emphasis_does_not_cross_paragraphs(self):
        self.assertEqual(render_document("*a\n\nb*"), "<p>*a</p>\n<p>b*</p>")
        self.assertEqual(render_document("*a\n# h\nb*"), "<p>*a</p>\n<h1>h</h1>\n<p>b*</p>")


class Differential(unittest.TestCase):
    def run_alphabet(self, seed, count, alphabet, maxlen):
        rng = random.Random(seed)
        for _ in range(count):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, maxlen + 1)))
            self.assertEqual(render_inline(s), ref_html(s), repr(s))
            self.assertEqual(plain_text(s), ref_plain(s), repr(s))

    def test_stars_and_letters(self):
        self.run_alphabet(1, 4000, ["*", "*", "a", "b", " "], 14)

    def test_underscores_and_letters(self):
        self.run_alphabet(2, 4000, ["_", "_", "a", "b", " "], 14)

    def test_mixed_delimiters(self):
        self.run_alphabet(3, 5000, ["*", "_", "a", " ", "*", "_"], 16)

    def test_punctuation_neighbours(self):
        self.run_alphabet(4, 5000, ["*", "_", "a", ".", "(", ")", '"', "-", " "], 16)

    def test_escapes_code_and_newlines(self):
        self.run_alphabet(5, 5000, ["*", "_", "a", "\\", "`", "\n", " ", "*"], 16)

    def test_unicode_mix(self):
        self.run_alphabet(6, 4000, ["*", "_", "a", "\u20ac", "\u00a0", "\u2014", "\u00e9", " ", "\u3002"], 14)

    def test_long_runs(self):
        rng = random.Random(7)
        for _ in range(1500):
            parts = []
            for _ in range(rng.randrange(1, 6)):
                parts.append(rng.choice("*_") * rng.randrange(1, 7))
                parts.append(rng.choice(["a", "b c", " ", "x.y", ""]))
            s = "".join(parts)
            self.assertEqual(render_inline(s), ref_html(s), repr(s))

    def test_words_and_sentences(self):
        rng = random.Random(8)
        words = ["foo", "bar", "baz", "snake_case", "*args", "a*b", "(x)", "_u_", "**k**", "q.", "\u00e9t\u00e9", "2*3"]
        for _ in range(2500):
            s = " ".join(rng.choice(words) + rng.choice(["", "*", "**", "_", "__"]) for _ in range(rng.randrange(1, 7)))
            self.assertEqual(render_inline(s), ref_html(s), repr(s))


class Performance(unittest.TestCase):
    def timed(self, text, limit=4.0):
        t = time.perf_counter()
        out = render_inline(text)
        self.assertLess(time.perf_counter() - t, limit, text[:30])
        return out

    def test_many_unmatched_openers(self):
        self.timed("*a " * 40000)
        self.timed("_a " * 40000)
        self.timed("**a " * 30000)

    def test_many_unmatched_closers(self):
        self.timed("a* " * 40000)
        self.timed(" a*" * 40000)
        self.timed("a_ " * 40000)

    def test_rule_of_three_pathological(self):
        out = self.timed("*a**" * 20000)
        self.assertIn("a", out)
        self.timed("**a*" * 20000)
        self.timed("_*" * 25000)
        self.timed("*_*_ " * 12000)
        self.timed("a***b**" * 8000)

    def test_alternating_openers_and_closers(self):
        self.timed("*a* " * 30000)
        self.timed("(*a" * 20000 + "*)" * 20000)
        self.timed("*a _b " * 15000 + "_ *" * 15000)

    def test_deep_nesting_does_not_overflow_the_stack(self):
        n = 12000
        out = self.timed("*" * n + "x" + "*" * n)
        self.assertEqual(out.count("<strong>"), n // 2)
        self.assertEqual(out.count("<em>"), 0)
        self.assertEqual(plain_text("*" * n + "x" + "*" * n), "x")
        n = 6000
        out = self.timed("_*" * n + "x" + "*_" * n)
        self.assertGreater(out.count("<em>"), 1000)
        small = "_*" * 150 + "x" + "*_" * 150
        self.assertEqual(render_inline(small), ref_html(small))
        self.assertEqual(plain_text("**" * 7000 + "x" + "**" * 7000), "x")

    def test_long_plain_text_and_code_spans(self):
        out = self.timed("word " * 100000)
        self.assertEqual(len(out), 500000)
        self.timed("`a` " * 30000)
        self.timed("`" * 100000)
        self.timed("`a" * 40000 + "``")

    def test_big_random_document_matches_reference_on_slices(self):
        rng = random.Random(9)
        s = "".join(rng.choice(["*", "_", "a", " ", "b", "**", "__", "."]) for _ in range(30000))
        out = self.timed(s)
        self.assertEqual(out.replace("<em>", "").replace("</em>", "").replace("<strong>", "").replace("</strong>", "")
                         .replace("*", "").replace("_", ""), s.replace("*", "").replace("_", ""))
        for k in range(0, 3000, 500):
            piece = s[k:k + 300]
            self.assertEqual(render_inline(piece), ref_html(piece))


class Regression(unittest.TestCase):
    def test_old_behaviour(self):
        self.assertEqual(render_inline('a < b & "c" > d'), "a &lt; b &amp; &quot;c&quot; &gt; d")
        self.assertEqual(render_inline(r"\*not\* \_em\_ \a \\"), "*not* _em_ \\a \\")
        self.assertEqual(render_inline("a\nb"), "a\nb")
        self.assertEqual(render_inline("`a < b`"), "<code>a &lt; b</code>")
        self.assertEqual(render_inline("`` a`b ``"), "<code>a`b</code>")
        self.assertEqual(render_inline("`  `"), "<code>  </code>")
        self.assertEqual(render_inline("` a\nb `"), "<code>a b</code>")
        self.assertEqual(render_inline("`unclosed"), "`unclosed")
        self.assertEqual(render_inline("``a` b``c`"), "<code>a` b</code>c`")
        self.assertEqual(render_inline("\\`a`"), "`a`")
        self.assertEqual(render_inline("2 * 3 _ 4"), "2 * 3 _ 4")
        self.assertEqual(plain_text(r"a \* `b<c` d"), "a * b<c d")
        md = "# Title\n\nfirst line\n second line\n\n\n## Sub\ntext"
        self.assertEqual(render_document(md), "<h1>Title</h1>\n<p>first line\nsecond line</p>\n<h2>Sub</h2>\n<p>text</p>")
        self.assertEqual(outline(md), [(1, "Title"), (2, "Sub")])
        self.assertEqual(render_document(""), "")


if __name__ == "__main__":
    unittest.main()
