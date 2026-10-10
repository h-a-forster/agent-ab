import unittest

from mdinline import outline, plain_text, render_document, render_inline


class Basics(unittest.TestCase):
    def test_escape_and_text(self):
        self.assertEqual(render_inline('a < b & "c" > d'), "a &lt; b &amp; &quot;c&quot; &gt; d")
        self.assertEqual(render_inline(r"\*not\* \_em\_ \a \\"), "*not* _em_ \\a \\")
        self.assertEqual(render_inline("a\nb"), "a\nb")

    def test_code_spans(self):
        self.assertEqual(render_inline("`a < b`"), "<code>a &lt; b</code>")
        self.assertEqual(render_inline("`` a`b ``"), "<code>a`b</code>")
        self.assertEqual(render_inline("`  `"), "<code>  </code>")
        self.assertEqual(render_inline("` a\nb `"), "<code>a b</code>")
        self.assertEqual(render_inline("`unclosed"), "`unclosed")
        self.assertEqual(render_inline("``a` b``c`"), "<code>a` b</code>c`")
        self.assertEqual(render_inline("\\`a`"), "`a`")

    def test_lone_stars_are_plain_text(self):
        self.assertEqual(render_inline("2 * 3 _ 4"), "2 * 3 _ 4")

    def test_plain_text(self):
        self.assertEqual(plain_text(r"a \* `b<c` d"), "a * b<c d")

    def test_document(self):
        md = "# Title\n\nfirst line\n second line\n\n\n## Sub\ntext"
        self.assertEqual(render_document(md),
                         "<h1>Title</h1>\n<p>first line\nsecond line</p>\n<h2>Sub</h2>\n<p>text</p>")
        self.assertEqual(outline(md), [(1, "Title"), (2, "Sub")])
        self.assertEqual(render_document(""), "")
