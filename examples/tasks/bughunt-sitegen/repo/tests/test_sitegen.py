import datetime
import unittest

from sitegen import RouteError, Site, TemplateError, render_string
from sitegen import frontmatter
from sitegen.collections import by_tag, sort_newest_first
from sitegen.content import load_pages
from sitegen.feed import rfc822
from sitegen.links import resolve_source
from sitegen.pagination import paginate
from sitegen.util import slugify, url_to_path

FILES = {
    "index.md": "---\ntitle: Home\n---\nWelcome to **my** site. See [about](about.md#team).",
    "about.md": "---\ntitle: About\n---\nAbout us",
    "posts/2024-03-05-alpha.md": "---\ntitle: Alpha\ntags: [news, tech]\n---\nFirst",
    "posts/2024-04-10-beta.md": "---\ntitle: Beta\ntags: [news]\n---\nSecond",
    "posts/hidden.md": "---\ntitle: Hidden\ndate: 2024-05-01\ndraft: true\n---\nNo",
}


class FrontMatterTests(unittest.TestCase):
    def test_split(self):
        meta, body = frontmatter.split("---\ntitle: Hi\ntags: [a, b]\ndraft: yes\nn: 3\nd: 2024-03-05\n---\nBody\n")
        self.assertEqual(meta, {"title": "Hi", "tags": ["a", "b"], "draft": True, "n": 3, "d": datetime.date(2024, 3, 5)})
        self.assertEqual(body, "Body\n")
        self.assertEqual(frontmatter.split("no meta"), ({}, "no meta"))


class RouteTests(unittest.TestCase):
    def test_urls(self):
        site = Site(FILES, {"permalinks": {"posts": "/blog/{year}/{slug}/"}})
        urls = {p.source: p.url for p in site.pages}
        self.assertEqual(urls["index.md"], "/")
        self.assertEqual(urls["about.md"], "/about/")
        self.assertEqual(urls["posts/2024-03-05-alpha.md"], "/blog/2024/alpha/")

    def test_conflict(self):
        with self.assertRaises(RouteError):
            Site({"a.md": "---\nslug: x\n---\n", "b.md": "---\nslug: x\n---\n"})


class PaginationTests(unittest.TestCase):
    def test_exact(self):
        pages = paginate(list(range(6)), 3, "/blog/")
        self.assertEqual([p.items for p in pages], [[0, 1, 2], [3, 4, 5]])
        self.assertEqual([p.url for p in pages], ["/blog/", "/blog/page/2/"])
        self.assertEqual((pages[0].prev_url, pages[0].next_url), (None, "/blog/page/2/"))
        self.assertEqual((pages[1].prev_url, pages[1].next_url), ("/blog/", None))

    def test_empty(self):
        (page,) = paginate([], 5, "/blog/")
        self.assertEqual((page.items, page.total), ([], 1))


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.site = Site(FILES, {"permalinks": {"posts": "/blog/{year}/{slug}/"}, "title": "Demo"})
        self.out = self.site.build()

    def test_outputs(self):
        self.assertEqual(sorted(self.out), [
            "about/index.html", "blog/2024/alpha/index.html", "blog/2024/beta/index.html", "blog/index.html",
            "feed.xml", "index.html", "sitemap.xml", "tags/news/index.html", "tags/tech/index.html"])

    def test_page_html_and_links(self):
        self.assertEqual(self.out["index.html"],
                         '<article><h1>Home</h1><p>Welcome to <strong>my</strong> site. See <a href="/about/#team">about</a>.</p></article>')

    def test_blog_index_order(self):
        self.assertEqual(self.out["blog/index.html"].count("<li>"), 2)
        self.assertLess(self.out["blog/index.html"].index("Beta"), self.out["blog/index.html"].index("Alpha"))

    def test_draft_page_not_rendered(self):
        self.assertFalse(any("hidden" in path for path in self.out))

    def test_feed(self):
        feed = self.out["feed.xml"]
        self.assertIn("<title>Demo</title>", feed)
        self.assertLess(feed.index("Beta"), feed.index("Alpha"))
        self.assertIn("<pubDate>Wed, 10 Apr 2024 00:00:00 +0000</pubDate>", feed)


class TemplateTests(unittest.TestCase):
    def test_basics(self):
        self.assertEqual(render_string("Hi {{ name | upper }}!", {"name": "bob"}), "Hi BOB!")
        self.assertEqual(render_string("{{ x }}", {"x": "<b>"}), "&lt;b&gt;")
        self.assertEqual(render_string("{% for i in xs %}{{ i }}{% endfor %}", {"xs": [1, 2, 3]}), "123")
        self.assertEqual(render_string("{% if a %}y{% else %}n{% endif %}", {"a": 0}), "n")

    def test_errors(self):
        for bad in ("{% for x %}{% endfor %}", "{% if a %}", "{{ a | nope }}", "{% endif %}"):
            with self.assertRaises(TemplateError):
                render_string(bad, {"a": 1})


class HelperTests(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")
        self.assertEqual(url_to_path("/a/b/"), "a/b/index.html")
        self.assertEqual(resolve_source("docs/a.md", "b.md"), "docs/b.md")
        self.assertEqual(rfc822(datetime.date(2024, 3, 5)), "Tue, 05 Mar 2024 00:00:00 +0000")

    def test_collections(self):
        pages = load_pages(FILES)
        ordered = sort_newest_first([p for p in pages if p.section == "posts" and not p.draft])
        self.assertEqual([p.title for p in ordered], ["Beta", "Alpha"])
        self.assertEqual(list(by_tag(pages)), ["news", "tech"])


if __name__ == "__main__":
    unittest.main()
