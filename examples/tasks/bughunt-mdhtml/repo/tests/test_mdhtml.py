import unittest

from mdhtml import Slugger, escape_attr, escape_text, render, render_document, render_inline, slugify
from mdhtml.frontmatter import split_frontmatter
from mdhtml.textstats import extract_links, reading_time, to_plain_text, word_count


class InlineTests(unittest.TestCase):
    def test_emphasis(self):
        self.assertEqual(render_inline("*a* **b** ~~c~~"), "<em>a</em> <strong>b</strong> <del>c</del>")

    def test_code_span(self):
        self.assertEqual(render_inline("use `x < y` here"), "use <code>x &lt; y</code> here")

    def test_link_and_image(self):
        self.assertEqual(render_inline("[t](http://a.com)"), '<a href="http://a.com">t</a>')
        self.assertEqual(render_inline('![alt](p.png "T")'), '<img src="p.png" alt="alt" title="T">')

    def test_escape(self):
        self.assertEqual(escape_text("a < b & c"), "a &lt; b &amp; c")
        self.assertEqual(escape_attr('a"b'), "a&quot;b")


class BlockTests(unittest.TestCase):
    def test_heading_and_paragraph(self):
        self.assertEqual(render("# Alpha one\n\ntext"), '<h1 id="alpha-one">Alpha one</h1>\n<p>text</p>')

    def test_tight_list(self):
        self.assertEqual(render("- a\n- b"), "<ul>\n<li>a</li>\n<li>b</li>\n</ul>")

    def test_loose_list(self):
        self.assertEqual(render("- a\n\n- b"), "<ul>\n<li><p>a</p>\n</li>\n<li><p>b</p>\n</li>\n</ul>")

    def test_ordered_start(self):
        self.assertEqual(render("3. a\n4. b"), '<ol start="3">\n<li>a</li>\n<li>b</li>\n</ol>')

    def test_fence(self):
        self.assertEqual(render("```py\nx = 1\n```"), '<pre><code class="language-py">x = 1\n</code></pre>')

    def test_quote(self):
        self.assertEqual(render("> hi"), "<blockquote>\n<p>hi</p>\n</blockquote>")

    def test_table(self):
        html = render("| A | B |\n|:--|--:|\n| 1 | 2 |")
        self.assertIn('<th align="left">A</th><th align="right">B</th>', html)
        self.assertIn('<td align="left">1</td><td align="right">2</td>', html)

    def test_rule(self):
        self.assertEqual(render("---"), "<hr>")


class SlugTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")
        self.assertEqual(slugify("!!!"), "section")

    def test_toc(self):
        doc = render_document("# Gamma\n## Delta\n## Epsilon\n# Zeta")
        self.assertEqual(doc.toc(), "\n".join([
            "<ul>", '<li><a href="#gamma">Gamma</a>', "<ul>", '<li><a href="#delta">Delta</a></li>',
            '<li><a href="#epsilon">Epsilon</a></li>', "</ul>", "</li>", '<li><a href="#zeta">Zeta</a></li>', "</ul>"]))

    def test_toc_depth(self):
        doc = render_document("# Eta\n## Theta\n### Iota")
        self.assertNotIn("Iota", doc.toc(max_depth=2))
        self.assertIn("Iota", doc.toc(max_depth=3))

    def test_dups_in_one_doc(self):
        doc = render_document("# Kappa\n# Kappa")
        self.assertEqual(doc.ids(), ["kappa", "kappa-1"])


class ExtrasTests(unittest.TestCase):
    def test_frontmatter(self):
        meta, body = split_frontmatter("---\ntitle: Hi\ndraft: yes\n---\n# Body")
        self.assertEqual(meta, {"title": "Hi", "draft": True})
        self.assertEqual(body, "# Body")

    def test_stats(self):
        self.assertEqual(word_count("# One two\n\nthree `four`"), 4)
        self.assertEqual(reading_time("word " * 201), 2)
        self.assertEqual(extract_links("[a](u) ![i](p.png)"), [("a", "u")])
        self.assertIn("three", to_plain_text("para three"))


if __name__ == "__main__":
    unittest.main()
