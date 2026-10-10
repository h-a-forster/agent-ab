import unittest

from mdhtml import Slugger, escape_attr, escape_text, render, render_document, render_inline, slugify
from mdhtml.frontmatter import split_frontmatter
from mdhtml.inline import plain_text
from mdhtml.textstats import extract_links, reading_time, to_plain_text, word_count


class SlugSymptoms(unittest.TestCase):
    def test_render_twice_same_ids(self):
        self.assertEqual(render("# Intro"), '<h1 id="intro">Intro</h1>')
        self.assertEqual(render("# Intro"), '<h1 id="intro">Intro</h1>')
        self.assertEqual(render("# Intro"), '<h1 id="intro">Intro</h1>')

    def test_duplicates_within_document_only(self):
        for _ in range(3):
            doc = render_document("# Intro\n## Intro\n## Intro")
            self.assertEqual(doc.ids(), ["intro", "intro-1", "intro-2"])

    def test_independent_sluggers(self):
        a, b = Slugger(), Slugger()
        self.assertEqual(a.slug("Topic"), "topic")
        self.assertEqual(b.slug("Topic"), "topic")
        self.assertEqual(a.slug("Topic"), "topic-1")
        self.assertEqual(b.slug("Topic"), "topic-1")
        self.assertEqual(Slugger().slug("Topic"), "topic")

    def test_generated_id_never_collides(self):
        doc = render_document("# Part\n# Part\n# Part 1\n# Part")
        self.assertEqual(doc.ids(), ["part", "part-1", "part-1-1", "part-2"])

    def test_toc_links_use_the_same_unique_ids(self):
        doc = render_document("# Intro\n## Intro\n## Details\n# Intro")
        self.assertEqual(doc.ids(), ["intro", "intro-1", "details", "intro-2"])
        self.assertEqual(doc.toc(), "\n".join([
            "<ul>",
            '<li><a href="#intro">Intro</a>',
            "<ul>",
            '<li><a href="#intro-1">Intro</a></li>',
            '<li><a href="#details">Details</a></li>',
            "</ul>",
            "</li>",
            '<li><a href="#intro-2">Intro</a></li>',
            "</ul>",
        ]))

    def test_toc_anchors_match_heading_ids_in_second_document(self):
        render_document("# Overview\n# Overview")
        doc = render_document("# Overview\n# Overview")
        self.assertEqual(doc.ids(), ["overview", "overview-1"])
        for ident in doc.ids():
            self.assertIn('id="%s"' % ident, doc.html)
            self.assertIn('href="#%s"' % ident, doc.toc())

    def test_toc_for_inline_markup_headings(self):
        doc = render_document("## Using `foo()`\n## Using `foo()`")
        self.assertEqual(doc.ids(), ["using-foo", "using-foo-1"])
        self.assertIn('<li><a href="#using-foo-1">Using <code>foo()</code></a></li>', doc.toc())

    def test_toc_with_punctuation_heading_in_repeats(self):
        doc = render_document("# Q&A\n# Q&A\n# ???\n# ???")
        self.assertEqual(doc.ids(), ["qa", "qa-1", "section", "section-1"])
        toc = doc.toc()
        for ident in doc.ids():
            self.assertIn('href="#%s"' % ident, toc)

    def test_outline_and_depth_with_duplicates(self):
        doc = render_document("# Top\n## Same\n## Same\n### Deep")
        self.assertEqual(doc.outline(max_depth=2), "Top\n  Same\n  Same")
        self.assertEqual(doc.toc(max_depth=2).count("<a href"), 3)
        self.assertIn('href="#same-1"', doc.toc(max_depth=2))


class CodeSpanSymptoms(unittest.TestCase):
    def test_star_in_code(self):
        self.assertEqual(render_inline("`a*b*c`"), "<code>a*b*c</code>")
        self.assertEqual(render("`a*b*c`"), "<p><code>a*b*c</code></p>")

    def test_dunder(self):
        self.assertEqual(render_inline("call `__init__` now"), "call <code>__init__</code> now")
        self.assertEqual(render_inline("`_x_` and `**kw**` and `~~t~~`"), "<code>_x_</code> and <code>**kw**</code> and <code>~~t~~</code>")

    def test_emphasis_around_code_still_works(self):
        self.assertEqual(render_inline("**`x`**"), "<strong><code>x</code></strong>")
        self.assertEqual(render_inline("*see `a_b` now*"), "<em>see <code>a_b</code> now</em>")

    def test_in_headings_tables_lists_quotes(self):
        self.assertEqual(render("## The `*` and `**` operators"), '<h2 id="the-and-operators">The <code>*</code> and <code>**</code> operators</h2>')
        html = render("| A |\n|---|\n| `a*b*c` |")
        self.assertIn("<td><code>a*b*c</code></td>", html)
        self.assertEqual(render("- `x*y*z`"), "<ul>\n<li><code>x*y*z</code></li>\n</ul>")
        self.assertEqual(render("> `__a__`"), "<blockquote>\n<p><code>__a__</code></p>\n</blockquote>")

    def test_link_text_with_code(self):
        self.assertEqual(render_inline("[`a_b_c`](u)"), '<a href="u"><code>a_b_c</code></a>')
        self.assertEqual(render_inline("[`*x*`](u)"), '<a href="u"><code>*x*</code></a>')

    def test_backslash_escapes_are_literal(self):
        self.assertEqual(render_inline("\\*not em\\*"), "*not em*")
        self.assertEqual(render_inline("\\_a\\_ and \\*\\*b\\*\\*"), "_a_ and **b**")
        self.assertEqual(render("\\# not a heading"), "<p># not a heading</p>")
        self.assertEqual(render_inline("\\<b\\>"), "&lt;b&gt;")

    def test_code_html_escaping(self):
        self.assertEqual(render_inline("`<b>&amp;</b>`"), "<code>&lt;b&gt;&amp;amp;&lt;/b&gt;</code>")


class AttributeSymptoms(unittest.TestCase):
    def test_link_href(self):
        self.assertEqual(render_inline('[x](http://a.com/?q="1"&b=2)'), '<a href="http://a.com/?q=&quot;1&quot;&amp;b=2">x</a>')
        self.assertEqual(render_inline('[x](/a"b)'), '<a href="/a&quot;b">x</a>')

    def test_image(self):
        self.assertEqual(render_inline('![say "hi"](u.png)'), '<img src="u.png" alt="say &quot;hi&quot;">')
        self.assertEqual(render_inline('![a](u.png?x="1"&y=2)'), '<img src="u.png?x=&quot;1&quot;&amp;y=2" alt="a">')

    def test_autolink(self):
        self.assertEqual(render_inline('<http://a.com/?q="x">'), '<a href="http://a.com/?q=&quot;x&quot;">http://a.com/?q="x"</a>')

    def test_in_blocks(self):
        self.assertEqual(render('[x](/a"b)'), '<p><a href="/a&quot;b">x</a></p>')
        self.assertIn('<td><a href="/a&quot;b">x</a></td>', render('| A |\n|---|\n| [x](/a"b) |'))

    def test_plain_attributes_unchanged(self):
        self.assertEqual(render_inline('[x](http://a.com/p?a=1&b=2 "Title")'), '<a href="http://a.com/p?a=1&amp;b=2" title="Title">x</a>')
        self.assertEqual(render_inline("![a & b](u.png)"), '<img src="u.png" alt="a &amp; b">')


class LooseListSymptoms(unittest.TestCase):
    LOOSE3 = "<ul>\n<li><p>a</p>\n</li>\n<li><p>b</p>\n</li>\n<li><p>c</p>\n</li>\n</ul>"

    def test_blank_only_between_first_two(self):
        self.assertEqual(render("- a\n\n- b\n- c"), self.LOOSE3)

    def test_blank_only_before_last(self):
        self.assertEqual(render("- a\n- b\n\n- c"), self.LOOSE3)

    def test_blank_in_middle_of_four(self):
        html = render("- a\n- b\n\n- c\n- d")
        self.assertEqual(html.count("<p>"), 4)

    def test_ordered(self):
        self.assertEqual(render("1. a\n\n2. b\n3. c"), '<ol>\n<li><p>a</p>\n</li>\n<li><p>b</p>\n</li>\n<li><p>c</p>\n</li>\n</ol>')

    def test_nested_decides_for_itself(self):
        html = render("- a\n  - x\n\n  - y\n  - z\n- b")
        self.assertEqual(html, "\n".join([
            "<ul>", "<li>a", "<ul>", "<li><p>x</p>", "</li>", "<li><p>y</p>", "</li>", "<li><p>z</p>", "</li>", "</ul>", "</li>",
            "<li>b</li>", "</ul>"]))

    def test_tight_stays_tight(self):
        self.assertEqual(render("- a\n- b\n- c"), "<ul>\n<li>a</li>\n<li>b</li>\n<li>c</li>\n</ul>")
        self.assertEqual(render("* a\n  b\n* c"), "<ul>\n<li>a\nb</li>\n<li>c</li>\n</ul>")


class TableSymptoms(unittest.TestCase):
    def test_escaped_pipe_in_body(self):
        html = render("| A | B |\n|---|---|\n| a \\| b | c |")
        self.assertIn("<tr><td>a | b</td><td>c</td></tr>", html)

    def test_escaped_pipe_in_header(self):
        html = render("| A \\| B | C |\n|---|---|\n| 1 | 2 |")
        self.assertIn("<tr><th>A | B</th><th>C</th></tr>", html)
        self.assertIn("<tr><td>1</td><td>2</td></tr>", html)

    def test_without_outer_pipes(self):
        html = render("A \\| B | C\n--|--\n1 \\| 2 | 3")
        self.assertIn("<tr><th>A | B</th><th>C</th></tr>", html)
        self.assertIn("<tr><td>1 | 2</td><td>3</td></tr>", html)

    def test_several_escapes_and_edges(self):
        html = render("|a|b|\n|-|-|\n|\\|x\\||y|\n|p\\|||")
        self.assertIn("<tr><td>|x|</td><td>y</td></tr>", html)
        self.assertIn("<tr><td>p|</td><td></td></tr>", html)

    def test_pipe_inside_inline_markup_cell(self):
        html = render("| A | B |\n|---|---|\n| **x \\| y** | `z` |")
        self.assertIn("<td><strong>x | y</strong></td><td><code>z</code></td>", html)


class FenceSymptoms(unittest.TestCase):
    def test_longer_fence_holds_shorter(self):
        self.assertEqual(render("````\n```\ncode\n```\n````"), "<pre><code>```\ncode\n```\n</code></pre>")

    def test_tilde(self):
        self.assertEqual(render("~~~~\n~~~\nx\n~~~\n~~~~"), "<pre><code>~~~\nx\n~~~\n</code></pre>")

    def test_followed_by_paragraph(self):
        self.assertEqual(render("`````\n````\n`````\n\nafter"), "<pre><code>````\n</code></pre>\n<p>after</p>")

    def test_in_quote_and_list(self):
        self.assertEqual(render("> ````\n> ```\n> x\n> ```\n> ````"),
                         "<blockquote>\n<pre><code>```\nx\n```\n</code></pre>\n</blockquote>")
        self.assertIn("<pre><code>```\ny\n```\n</code></pre>", render("- item\n\n  ````\n  ```\n  y\n  ```\n  ````"))

    def test_longer_closing_fence_ok(self):
        self.assertEqual(render("```\ncode\n`````\n\nx"), "<pre><code>code\n</code></pre>\n<p>x</p>")

    def test_info_string_after_close_is_content(self):
        self.assertEqual(render("````\n```python\nx\n```\n````"), "<pre><code>```python\nx\n```\n</code></pre>")


class InlineRegression(unittest.TestCase):
    def test_emphasis_forms(self):
        self.assertEqual(render_inline("*a* _b_ **c** __d__ ~~e~~"), "<em>a</em> <em>b</em> <strong>c</strong> <strong>d</strong> <del>e</del>")
        self.assertEqual(render_inline("**a *b* c**"), "<strong>a <em>b</em> c</strong>")

    def test_intraword_underscore_and_stars(self):
        self.assertEqual(render_inline("snake_case_name"), "snake_case_name")
        self.assertEqual(render_inline("2*3*4"), "2*3*4")
        self.assertEqual(render_inline("a*b"), "a*b")
        self.assertEqual(render_inline("__init__"), "<strong>init</strong>")

    def test_escape_text_entities(self):
        self.assertEqual(render_inline("AT&T &amp; &copy; &#169; &#xA9; 1 < 2 > 0"), "AT&amp;T &amp; &copy; &#169; &#xA9; 1 &lt; 2 &gt; 0")
        self.assertEqual(escape_text('"quote"'), '"quote"')
        self.assertEqual(escape_attr('"quote" & <'), "&quot;quote&quot; &amp; &lt;")

    def test_links(self):
        self.assertEqual(render_inline('[l](http://x.com "Tt")'), '<a href="http://x.com" title="Tt">l</a>')
        self.assertEqual(render_inline("[*em*](u)"), '<a href="u"><em>em</em></a>')
        self.assertEqual(render_inline("<https://a.com/x_y_z>"), '<a href="https://a.com/x_y_z">https://a.com/x_y_z</a>')
        self.assertEqual(render_inline("[a](b)(c)"), '<a href="b">a</a>(c)')
        self.assertEqual(render_inline("[a](http://x.com/a_b_c)"), '<a href="http://x.com/a_b_c">a</a>')

    def test_images(self):
        self.assertEqual(render_inline('![alt](img.png "T")'), '<img src="img.png" alt="alt" title="T">')
        self.assertEqual(render_inline("![](a.png)"), '<img src="a.png" alt="">')

    def test_hard_break(self):
        self.assertEqual(render_inline("a  \nb"), "a<br>\nb")
        self.assertEqual(render_inline("a \nb"), "a \nb")

    def test_code_spans(self):
        self.assertEqual(render_inline("``a`b``"), "<code>a`b</code>")
        self.assertEqual(render_inline("` a `"), "<code>a</code>")
        self.assertEqual(render_inline("`  `"), "<code>  </code>")
        self.assertEqual(render_inline("`a\nb`"), "<code>a b</code>")

    def test_plain_text(self):
        self.assertEqual(plain_text("Using `foo()` and *em* [l](u) ![i](p)"), "Using foo() and em l i")


class BlockRegression(unittest.TestCase):
    def test_headings(self):
        self.assertEqual(render("Title\n=====\n\nSub\n---"), '<h1 id="title">Title</h1>\n<h2 id="sub">Sub</h2>')
        self.assertEqual(render("## Closed ##"), '<h2 id="closed">Closed</h2>')
        self.assertEqual(render("####### seven"), "<p>####### seven</p>")
        self.assertEqual(render("#NoSpace"), "<p>#NoSpace</p>")
        self.assertEqual(render("#"), '<h1 id="section"></h1>')

    def test_heading_ids_option(self):
        doc = render_document("# A heading", ids=False)
        self.assertEqual(doc.html, "<h1>A heading</h1>")

    def test_paragraph_joining(self):
        self.assertEqual(render("one\ntwo\n\nthree"), "<p>one\ntwo</p>\n<p>three</p>")
        self.assertEqual(render("one\n   two"), "<p>one\ntwo</p>")

    def test_rules(self):
        self.assertEqual(render("* * *\n\n- - -\n\n___\n\n---"), "<hr>\n<hr>\n<hr>\n<hr>")
        self.assertEqual(render("para\n---"), '<h2 id="para">para</h2>')

    def test_quotes(self):
        self.assertEqual(render("> quote\ncontinued\n> > nested"),
                         "<blockquote>\n<p>quote\ncontinued</p>\n<blockquote>\n<p>nested</p>\n</blockquote>\n</blockquote>")
        self.assertEqual(render("> a\n\n> b"), "<blockquote>\n<p>a</p>\n</blockquote>\n<blockquote>\n<p>b</p>\n</blockquote>")

    def test_lists(self):
        self.assertEqual(render("- a\n- b\n\n* c\n* d"), "<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<ul>\n<li>c</li>\n<li>d</li>\n</ul>")
        self.assertEqual(render("0. zero\n1. one"), '<ol start="0">\n<li>zero</li>\n<li>one</li>\n</ol>')
        self.assertEqual(render("1) a\n2) b"), "<ol>\n<li>a</li>\n<li>b</li>\n</ol>")
        self.assertEqual(render("5. five"), '<ol start="5">\n<li>five</li>\n</ol>')

    def test_nested_lists(self):
        self.assertEqual(render("1. a\n   - b\n   - c\n2. d"),
                         "<ol>\n<li>a\n<ul>\n<li>b</li>\n<li>c</li>\n</ul>\n</li>\n<li>d</li>\n</ol>")
        self.assertEqual(render("- a\n\n  - x\n  - y\n- b"),
                         "<ul>\n<li>a\n<ul>\n<li>x</li>\n<li>y</li>\n</ul>\n</li>\n<li>b</li>\n</ul>")

    def test_list_interrupts_paragraph(self):
        self.assertEqual(render("text\n- a\n- b"), "<p>text</p>\n<ul>\n<li>a</li>\n<li>b</li>\n</ul>")
        self.assertEqual(render("text\n2. not a list"), "<p>text\n2. not a list</p>")

    def test_code_blocks(self):
        self.assertEqual(render("```python title=x\nx = 1 < 2 & 3\n```"), '<pre><code class="language-python">x = 1 &lt; 2 &amp; 3\n</code></pre>')
        self.assertEqual(render("```\n\n```"), "<pre><code>\n</code></pre>")
        self.assertEqual(render("~~~\nunclosed"), "<pre><code>unclosed\n</code></pre>")
        self.assertEqual(render("```\n```"), "<pre><code></code></pre>")
        self.assertEqual(render("```\n  indented\n```"), "<pre><code>  indented\n</code></pre>")

    def test_fence_not_closed_by_other_char_or_text(self):
        self.assertEqual(render("```\n~~~\n```x\n```"), "<pre><code>~~~\n```x\n</code></pre>")

    def test_tables(self):
        html = render("| A | B | C |\n|:--|:-:|--:|\n| 1 | 2 |\n| 1 | 2 | 3 | 4 |")
        self.assertEqual(html, "\n".join([
            "<table>", "<thead>",
            '<tr><th align="left">A</th><th align="center">B</th><th align="right">C</th></tr>', "</thead>", "<tbody>",
            '<tr><td align="left">1</td><td align="center">2</td><td align="right"></td></tr>',
            '<tr><td align="left">1</td><td align="center">2</td><td align="right">3</td></tr>', "</tbody>", "</table>"]))

    def test_table_header_only_and_no_outer_pipes(self):
        self.assertEqual(render("|x|\n|-|"), "<table>\n<thead>\n<tr><th>x</th></tr>\n</thead>\n</table>")
        self.assertIn("<tr><td>1</td><td>2</td></tr>", render("A | B\n--|--\n1 | 2"))

    def test_not_a_table(self):
        self.assertEqual(render("a | b\nc | d"), "<p>a | b\nc | d</p>")
        self.assertEqual(render("a | b\n--|--|--\n1"), "<p>a | b\n--|--|--\n1</p>")

    def test_line_endings_and_tabs(self):
        self.assertEqual(render("# A title\r\n\r\ntext\r\nmore"), '<h1 id="a-title">A title</h1>\n<p>text\nmore</p>')
        self.assertEqual(render(""), "")
        self.assertEqual(render("\n\n"), "")

    def test_empty_quote(self):
        self.assertEqual(render(">"), "<blockquote>\n</blockquote>")


class SlugHelpers(unittest.TestCase):
    def test_slugify(self):
        cases = {"Hello, World!": "hello-world", "  A  B  ": "a-b", "a_b-c": "a-b-c", "Ünïcode Straße!": "ünïcode-straße",
                 "---": "section", "": "section", "C++ & C#": "c-c", "2024 Plan": "2024-plan"}
        for text, expected in cases.items():
            self.assertEqual(slugify(text), expected, text)

    def test_slugger_used(self):
        s = Slugger()
        s.slug("b")
        s.slug("a")
        s.slug("a")
        self.assertEqual(s.used(), ["a", "a-1", "b"])


class TocRegression(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(render_document("just text").toc(), "")

    def test_depth_limits(self):
        doc = render_document("# One\n## Two\n### Three\n#### Four")
        self.assertEqual(doc.outline(), "One\n  Two\n    Three")
        self.assertEqual(doc.outline(max_depth=1), "One")
        self.assertEqual(doc.outline(max_depth=4), "One\n  Two\n    Three\n      Four")
        self.assertEqual(doc.outline(min_depth=2, max_depth=3), "Two\n  Three")
        self.assertEqual(doc.toc(max_depth=1), '<ul>\n<li><a href="#one">One</a></li>\n</ul>')

    def test_level_jumps(self):
        doc = render_document("# A\n### B\n## C\n# D")
        self.assertEqual(doc.outline(), "A\n  B\n  C\nD")

    def test_headings_metadata(self):
        doc = render_document("# *Hi* `x`")
        h = doc.headings[0]
        self.assertEqual((h.level, h.text, h.id, h.html), (1, "Hi x", "hi-x", "<em>Hi</em> <code>x</code>"))

    def test_headings_in_quotes_count(self):
        doc = render_document("> # In quote\n\n- # In list")
        self.assertEqual(doc.ids(), ["in-quote", "in-list"])


class FrontmatterAndStats(unittest.TestCase):
    def test_frontmatter(self):
        meta, body = split_frontmatter("---\ntitle: Hello: World\ntags: [a, b]\ndraft: yes\nn: 5\nq: \"x\"\n# c\n---\n# Body")
        self.assertEqual(meta, {"title": "Hello: World", "tags": ["a", "b"], "draft": True, "n": 5, "q": "x"})
        self.assertEqual(body, "# Body")
        self.assertEqual(split_frontmatter("# no meta"), ({}, "# no meta"))
        self.assertEqual(split_frontmatter("---\nnever closed"), ({}, "---\nnever closed"))

    def test_render_document_frontmatter(self):
        doc = render_document("---\ntitle: T\n---\n# Heading", frontmatter=True)
        self.assertEqual(doc.meta, {"title": "T"})
        self.assertEqual(doc.html, '<h1 id="heading">Heading</h1>')
        self.assertEqual(render_document("# H").meta, {})

    def test_plain_text_and_counts(self):
        text = "# T\n\nSome *em* `code` [l](u)\n\n```\nskip me\n```\n\n- a\n- b\n\n| X | Y |\n|---|---|\n| 1 | 2 |"
        self.assertEqual(to_plain_text(text), "T\nSome em code l\na\nb\nX\nY\n1\n2")
        self.assertEqual(word_count(text), 11)

    def test_reading_time(self):
        self.assertEqual(reading_time(""), 0)
        self.assertEqual(reading_time("word"), 1)
        self.assertEqual(reading_time("w " * 200), 1)
        self.assertEqual(reading_time("w " * 201), 2)
        self.assertEqual(reading_time("w " * 100, words_per_minute=50), 2)

    def test_extract_links(self):
        self.assertEqual(extract_links('[a](u) ![i](p.png) [b](v "t") text [c](w)'), [("a", "u"), ("b", "v"), ("c", "w")])


if __name__ == "__main__":
    unittest.main()
