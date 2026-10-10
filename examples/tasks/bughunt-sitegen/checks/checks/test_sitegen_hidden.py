import datetime
import unittest

from sitegen import FrontMatterError, RouteError, Site, SiteError, TemplateError, render_string
from sitegen import frontmatter, routes
from sitegen.collections import by_section, by_tag, by_year, neighbours, sort_newest_first
from sitegen.content import Page, load_pages
from sitegen.feed import build_feed, build_sitemap, rfc822
from sitegen.links import is_external, resolve_source, rewrite_links, split_fragment
from sitegen.markup import render_markdown
from sitegen.pagination import page_url, paginate
from sitegen.stats import posts_per_year, reading_minutes, summary, tag_counts, word_count
from sitegen.templates import Safe, evaluate
from sitegen.util import ensure_slashes, escape_html, join_url, slugify, url_to_path

D = datetime.date

FILES = {
    "index.md": "---\ntitle: Home\n---\nWelcome. See [about](about.md#team) and [first](posts/2024-03-05-alpha.md).",
    "about.md": "---\ntitle: About\n---\nAbout us.",
    "docs/index.md": "---\ntitle: Docs\n---\nDocs home",
    "docs/guide/setup.md": "---\ntitle: Setup\n---\nBack to [about](../../about.md), [docs](../index.md#top), "
                           "[intro](./intro.md), [same](intro.md), [abs](/about.md#x), [mid](x/../intro.md), "
                           "[gone](../nope.md), [ext](https://x.org/a.md), [img](../logo.png), [frag](#here).",
    "docs/guide/intro.md": "---\ntitle: Intro\n---\nIntro",
    "posts/2024-03-05-alpha.md": "---\ntitle: Alpha\ntags: [news, Tech]\n---\nFirst post",
    "posts/2024-03-05-zebra.md": "---\ntitle: Zebra\ntags: [news]\n---\nZ post",
    "posts/2024-03-05-mango.md": "---\ntitle: mango\ntags: [tech]\n---\nM post",
    "posts/2024-11-20-late.md": "---\ntitle: Late\ntags: [news]\n---\nLate post",
    "posts/2023-12-01-old.md": "---\ntitle: Old & Gold\n---\nOld post",
    "posts/wip.md": "---\ntitle: WIP\ndate: 2024-12-24\ndraft: true\ntags: [news, secret]\n---\nNot yet",
}
CONFIG = {"permalinks": {"posts": "/blog/{year}/{month}/{slug}/"}, "title": "Demo & Co", "per_page": 2}


def make_site(**extra):
    config = dict(CONFIG)
    config.update(extra)
    return Site(FILES, config)


class FrontMatterSymptoms(unittest.TestCase):
    def test_colon_in_value(self):
        meta, body = frontmatter.split("---\ntitle: Hello: World\n---\nbody")
        self.assertEqual(meta, {"title": "Hello: World"})
        self.assertEqual(body, "body")

    def test_more_colons(self):
        meta, _ = frontmatter.split("---\nsubtitle: A: B: C\nurl: http://x.org:8080/a\ntime: 09:30\nq: \"a: b\"\n---\n")
        self.assertEqual(meta, {"subtitle": "A: B: C", "url": "http://x.org:8080/a", "time": "09:30", "q": "a: b"})

    def test_page_title_with_colon(self):
        files = {"a.md": "---\ntitle: Part 1: The Start\ntags: [x: y]\n---\nBody"}
        page = Site(files).pages[0]
        self.assertEqual(page.title, "Part 1: The Start")
        self.assertEqual(Site(files).build()["a/index.html"], "<article><h1>Part 1: The Start</h1><p>Body</p></article>")

    def test_slug_and_date_from_meta_with_colon_elsewhere(self):
        files = {"p.md": "---\ntitle: T: U\nslug: custom\ndate: 2024-02-03\n---\nx"}
        page = Site(files).pages[0]
        self.assertEqual((page.slug, page.date, page.url), ("custom", D(2024, 2, 3), "/custom/"))

    def test_no_colon_error_and_unclosed(self):
        with self.assertRaises(FrontMatterError):
            frontmatter.split("---\njust text\n---\nbody")
        with self.assertRaises(FrontMatterError):
            frontmatter.split("---\ntitle: x\nbody")


class PermalinkSymptoms(unittest.TestCase):
    def test_month_and_day_padded(self):
        files = {"posts/2024-03-05-alpha.md": "a", "posts/2024-11-20-late.md": "b"}
        site = Site(files, {"permalinks": {"posts": "/blog/{year}/{month}/{day}/{slug}/"}})
        self.assertEqual([p.url for p in site.pages], ["/blog/2024/03/05/alpha/", "/blog/2024/11/20/late/"])

    def test_month_only_patterns(self):
        files = {"posts/2024-03-05-alpha.md": "a", "posts/2024-01-31-new-year.md": "b"}
        site = Site(files, {"permalinks": {"posts": "/archive/{year}-{month}/{slug}/"}})
        self.assertEqual([p.url for p in site.pages], ["/archive/2024-01/new-year/", "/archive/2024-03/alpha/"])

    def test_output_paths(self):
        out = make_site().build()
        self.assertIn("blog/2024/03/alpha/index.html", out)
        self.assertIn("blog/2024/11/late/index.html", out)
        self.assertIn("blog/2023/12/old/index.html", out)

    def test_front_matter_permalink_and_default_pattern(self):
        files = {"a.md": "---\npermalink: /x/{year}/{month}/\ndate: 2024-02-09\n---\n", "b.md": "---\ndate: 2025-07-01\n---\n"}
        site = Site(files, {"permalinks": {"default": "/{year}/{month}/{slug}/"}})
        self.assertEqual([p.url for p in site.pages], ["/x/2024/02/", "/2025/07/b/"])

    def test_title_placeholder_uses_padding_too(self):
        files = {"posts/2024-05-06-x.md": "---\ntitle: Big News!\n---\n"}
        site = Site(files, {"permalinks": {"posts": "/{year}/{month}/{day}/{title}/"}})
        self.assertEqual(site.pages[0].url, "/2024/05/06/big-news/")


class PaginationSymptoms(unittest.TestCase):
    def test_remainder_gets_a_page(self):
        pages = paginate(list(range(7)), 3, "/blog/")
        self.assertEqual([p.items for p in pages], [[0, 1, 2], [3, 4, 5], [6]])
        self.assertEqual([p.url for p in pages], ["/blog/", "/blog/page/2/", "/blog/page/3/"])
        self.assertEqual([p.total for p in pages], [3, 3, 3])
        self.assertEqual((pages[2].prev_url, pages[2].next_url), ("/blog/page/2/", None))
        self.assertEqual((pages[1].prev_url, pages[1].next_url), ("/blog/", "/blog/page/3/"))

    def test_other_sizes(self):
        self.assertEqual([len(p.items) for p in paginate(list(range(11)), 5, "/b/")], [5, 5, 1])
        self.assertEqual([len(p.items) for p in paginate(list(range(5)), 3, "/b/")], [3, 2])
        self.assertEqual([len(p.items) for p in paginate(list(range(1)), 5, "/b/")], [1])
        self.assertEqual([len(p.items) for p in paginate(list(range(4)), 1, "/b/")], [1, 1, 1, 1])
        self.assertEqual([len(p.items) for p in paginate(list(range(2)), 10, "/b/")], [2])

    def test_site_blog_pages(self):
        out = make_site().build()
        self.assertIn("blog/index.html", out)
        self.assertIn("blog/page/2/index.html", out)
        self.assertIn("blog/page/3/index.html", out)
        self.assertNotIn("blog/page/4/index.html", out)
        listed = sum(out[p].count("<li>") for p in ("blog/index.html", "blog/page/2/index.html", "blog/page/3/index.html"))
        self.assertEqual(listed, 5)
        self.assertIn("Old &amp; Gold", out["blog/page/3/index.html"])

    def test_site_all_posts_reachable(self):
        out = make_site(per_page=4).build()
        text = out["blog/index.html"] + out["blog/page/2/index.html"]
        for title in ("Alpha", "Zebra", "mango", "Late", "Old"):
            self.assertIn(title, text)


class OrderingSymptoms(unittest.TestCase):
    def pages(self, names_dates):
        return [Page("posts/%s.md" % t.lower(), {"title": t, "date": d}, "") for t, d in names_dates]

    def test_same_date_by_title(self):
        pages = self.pages([("Zebra", D(2024, 3, 5)), ("Alpha", D(2024, 3, 5)), ("Mango", D(2024, 3, 5))])
        self.assertEqual([p.title for p in sort_newest_first(pages)], ["Alpha", "Mango", "Zebra"])

    def test_mixed_dates_and_case(self):
        pages = self.pages([("b", D(2024, 1, 1)), ("Zed", D(2024, 6, 1)), ("apple", D(2024, 1, 1)), ("Ant", D(2024, 6, 1)),
                            ("Old", D(2020, 1, 1))])
        self.assertEqual([p.title for p in sort_newest_first(pages)], ["Ant", "Zed", "apple", "b", "Old"])

    def test_undated_last(self):
        pages = self.pages([("Zeta", D(2024, 1, 1))]) + [Page("n2.md", {"title": "B-undated"}, ""), Page("n1.md", {"title": "A-undated"}, "")]
        self.assertEqual([p.title for p in sort_newest_first(pages)], ["Zeta", "A-undated", "B-undated"])

    def test_blog_index_feed_and_tags(self):
        out = make_site(per_page=10).build()
        index = out["blog/index.html"]
        order = [index.index(t) for t in ("Late", "Alpha", "mango", "Zebra", "Old")]
        self.assertEqual(order, sorted(order))
        feed = out["feed.xml"]
        order = [feed.index("<title>%s</title>" % t) for t in ("Late", "Alpha", "mango", "Zebra")]
        self.assertEqual(order, sorted(order))
        news = out["tags/news/index.html"]
        order = [news.index(t) for t in ("Late", "Alpha", "Zebra")]
        self.assertEqual(order, sorted(order))

    def test_collection_helpers(self):
        site = make_site()
        published = site.published()
        self.assertEqual([p.title for p in by_section(published, "posts")], ["Late", "Alpha", "mango", "Zebra", "Old & Gold"])
        tags = by_tag(published)
        self.assertEqual([p.title for p in tags["news"]], ["Late", "Alpha", "Zebra"])
        self.assertEqual([p.title for p in tags["Tech"]], ["Alpha", "mango"])
        years = by_year(published)
        self.assertEqual(list(years), [2024, 2023])
        self.assertEqual([p.title for p in years[2024]], ["Late", "Alpha", "mango", "Zebra"])

    def test_neighbours(self):
        posts = by_section(make_site().published(), "posts")
        newer, older = neighbours(posts, posts[2])
        self.assertEqual((newer.title, older.title), ("Alpha", "Zebra"))
        self.assertEqual(neighbours(posts, posts[0])[0], None)
        self.assertEqual(neighbours(posts, posts[-1])[1], None)

    def test_feed_limit_respects_order(self):
        out = make_site(feed_limit=3).build()
        feed = out["feed.xml"]
        self.assertEqual(feed.count("<item>"), 3)
        self.assertIn("<title>Alpha</title>", feed)
        self.assertNotIn("<title>Zebra</title>", feed)


class DraftSymptoms(unittest.TestCase):
    def test_feed_excludes_drafts(self):
        out = make_site().build()
        self.assertNotIn("WIP", out["feed.xml"])
        self.assertNotIn("wip", out["feed.xml"])
        self.assertEqual(out["feed.xml"].count("<item>"), 5)

    def test_sitemap_excludes_drafts(self):
        out = make_site().build()
        self.assertNotIn("wip", out["sitemap.xml"])
        self.assertNotIn("2024-12-24", out["sitemap.xml"])
        self.assertEqual(out["sitemap.xml"].count("<url>"), 10)

    def test_newest_draft_would_be_first(self):
        files = {"posts/2024-01-01-a.md": "---\ntitle: A\n---\n", "posts/b.md": "---\ntitle: B\ndate: 2030-01-01\ndraft: true\n---\n"}
        out = Site(files, {}).build()
        self.assertEqual(out["feed.xml"].count("<item>"), 1)
        self.assertNotIn("<title>B</title>", out["feed.xml"])
        self.assertNotIn("/b/", out["sitemap.xml"])

    def test_include_drafts_flag(self):
        out = make_site(include_drafts=True).build()
        self.assertIn("<title>WIP</title>", out["feed.xml"])
        self.assertIn("wip", out["sitemap.xml"])
        self.assertIn("tags/secret/index.html", out)

    def test_drafts_elsewhere_still_hidden(self):
        out = make_site().build()
        self.assertNotIn("tags/secret/index.html", out)
        self.assertNotIn("WIP", out["tags/news/index.html"])
        self.assertFalse(any("wip" in path for path in out))
        self.assertEqual(summary(make_site())["drafts"], 1)


class LinkSymptoms(unittest.TestCase):
    def setUp(self):
        self.site = make_site()
        self.out = self.site.build()
        self.setup = self.out["setup/index.html"]

    def test_parent_directories(self):
        self.assertIn('<a href="/about/">about</a>', self.setup)
        self.assertIn('<a href="/docs/#top">docs</a>', self.setup)

    def test_dot_segments(self):
        self.assertIn('<a href="/intro/">intro</a>', self.setup)
        self.assertIn('<a href="/intro/">mid</a>', self.setup)
        self.assertIn('<a href="/intro/">same</a>', self.setup)

    def test_absolute_and_untouched(self):
        self.assertIn('<a href="/about/#x">abs</a>', self.setup)
        self.assertIn('<a href="https://x.org/a.md">ext</a>', self.setup)
        self.assertIn('<a href="../logo.png">img</a>', self.setup)
        self.assertIn('<a href="#here">frag</a>', self.setup)

    def test_broken_links_reported(self):
        self.assertEqual(self.site.broken_links, [("docs/guide/setup.md", "../nope.md")])
        self.assertIn('<a href="../nope.md">gone</a>', self.setup)
        self.assertEqual(summary(self.site)["broken_links"], 1)

    def test_resolve_source(self):
        self.assertEqual(resolve_source("docs/guide/setup.md", "../../about.md"), "about.md")
        self.assertEqual(resolve_source("docs/guide/setup.md", "./intro.md"), "docs/guide/intro.md")
        self.assertEqual(resolve_source("docs/guide/setup.md", "../index.md"), "docs/index.md")
        self.assertEqual(resolve_source("docs/guide/setup.md", "a/../b/./c.md"), "docs/guide/b/c.md")
        self.assertEqual(resolve_source("docs/guide/setup.md", "/about.md"), "about.md")
        self.assertEqual(resolve_source("index.md", "about.md"), "about.md")
        self.assertEqual(resolve_source("index.md", "./about.md"), "about.md")
        self.assertEqual(resolve_source("a/b.md", "../../c.md"), "../c.md")

    def test_rewrite_links_function(self):
        urls = {"about.md": "/about/", "docs/index.md": "/docs/"}
        broken = []
        text = "[a](../about.md#t) [b](./index.md) [c](../zzz.md)"
        self.assertEqual(rewrite_links(text, "docs/x.md", urls, broken), "[a](/about/#t) [b](/docs/) [c](../zzz.md)")
        self.assertEqual(broken, [("docs/x.md", "../zzz.md")])

    def test_link_to_draft_is_broken(self):
        files = {"a.md": "[d](posts/wip.md)", "posts/wip.md": "---\ndraft: true\n---\nx"}
        site = Site(files)
        site.build()
        self.assertEqual(site.broken_links, [("a.md", "posts/wip.md")])

    def test_top_level_pages_unchanged(self):
        self.assertIn('<a href="/about/#team">about</a>', self.out["index.html"])
        self.assertIn('<a href="/blog/2024/03/alpha/">first</a>', self.out["index.html"])


class TemplateScopeSymptoms(unittest.TestCase):
    def test_loop_variable_does_not_leak(self):
        self.assertEqual(render_string("{% for page in pages %}{{ page }},{% endfor %}{{ page }}", {"page": "outer", "pages": [1, 2]}), "1,2,outer")
        self.assertEqual(render_string("{% for x in xs %}{{ x }}{% endfor %}[{{ x }}]", {"xs": [1, 2]}), "12[]")

    def test_nested_loops_have_own_loop_variable(self):
        tpl = "{% for a in xs %}{% for b in ys %}{{ loop.index }}{% endfor %}-{{ loop.index }};{% endfor %}"
        self.assertEqual(render_string(tpl, {"xs": [1, 2], "ys": [1, 2, 3]}), "123-1;123-2;")

    def test_loop_helpers_after_nested_loop(self):
        tpl = "{% for a in xs %}{% for b in ys %}.{% endfor %}{% if loop.first %}F{% endif %}{% if loop.last %}L{% endif %}{% endfor %}"
        self.assertEqual(render_string(tpl, {"xs": [1, 2, 3], "ys": [1]}), ".F..L")

    def test_layout_page_not_clobbered(self):
        layout = "<h1>{{ page.title }}</h1>{% for page in pages %}<li>{{ page.title }}</li>{% endfor %}<f>{{ page.title }}</f>"
        files = {"a.md": "---\ntitle: Current\n---\nx", "b.md": "---\ntitle: Other\n---\ny"}
        out = Site(files, {"layouts": {"default": layout}}).build()
        self.assertEqual(out["a/index.html"], "<h1>Current</h1><li>Current</li><li>Other</li><f>Current</f>")
        self.assertEqual(out["b/index.html"], "<h1>Other</h1><li>Current</li><li>Other</li><f>Other</f>")

    def test_outer_variable_survives_loop_over_same_name(self):
        self.assertEqual(render_string("{{ item }}{% for item in items %}{{ item }}{% endfor %}{{ item }}", {"item": "X", "items": ["a", "b"]}), "XabX")

    def test_for_else_and_empty(self):
        self.assertEqual(render_string("{% for x in xs %}{{ x }}{% else %}none{% endfor %}", {"xs": []}), "none")
        self.assertEqual(render_string("{% for x in xs %}{{ x }}{% else %}none{% endfor %}", {}), "none")


class ParseRegression(unittest.TestCase):
    def test_scalars(self):
        meta, _ = frontmatter.split('---\na: "q"\nb: \'r\'\nc: [1, two, "3"]\nd: no\ne: ~\nf: 12\ng: 2024-02-29\nh: 2024-13-40\ni: []\n# comment\n\nj:\n---\n')
        self.assertEqual(meta, {"a": "q", "b": "r", "c": [1, "two", "3"], "d": False, "e": None, "f": 12,
                                "g": D(2024, 2, 29), "h": "2024-13-40", "i": [], "j": None})

    def test_crlf_and_body(self):
        meta, body = frontmatter.split("---\r\ntitle: X\r\n---\r\nline1\r\nline2")
        self.assertEqual((meta, body), ({"title": "X"}, "line1\nline2"))

    def test_page_attributes(self):
        files = {"posts/2024-03-05-hello-world.md": "---\ntags: news\n---\nb", "notes/2024-02-30-bad-date.md": "x",
                 "my_page-name.md": "---\ndate: 2024-01-02\nslug: Custom Slug!\n---\n", "readme.txt": "ignored"}
        pages = {p.source: p for p in load_pages(files)}
        self.assertEqual(sorted(pages), ["my_page-name.md", "notes/2024-02-30-bad-date.md", "posts/2024-03-05-hello-world.md"])
        p = pages["posts/2024-03-05-hello-world.md"]
        self.assertEqual((p.date, p.slug, p.title, p.tags, p.section), (D(2024, 3, 5), "hello-world", "Hello World", ["news"], "posts"))
        q = pages["notes/2024-02-30-bad-date.md"]
        self.assertEqual((q.date, q.slug), (None, "2024-02-30-bad-date"))
        r = pages["my_page-name.md"]
        self.assertEqual((r.date, r.slug, r.title, r.section), (D(2024, 1, 2), "custom-slug", "My Page Name", ""))

    def test_bad_meta_date(self):
        with self.assertRaises(SiteError):
            Page("a.md", {"date": "yesterday"}, "")

    def test_meta_date_beats_filename(self):
        page = Page("posts/2024-03-05-x.md", {"date": D(2025, 1, 1)}, "")
        self.assertEqual((page.date, page.slug), (D(2025, 1, 1), "x"))


class RouteRegression(unittest.TestCase):
    def urls(self, files, patterns=None):
        return {p.source: p.url for p in Site(files, {"permalinks": patterns or {}}).pages}

    def test_precedence(self):
        files = {
            "index.md": "", "docs/index.md": "", "docs/a.md": "", "docs/deep/index.md": "",
            "posts/2024-01-02-x.md": "", "u.md": "---\nurl: custom/place\n---\n", "f.md": "---\nurl: /feed.xml\n---\n",
            "p.md": "---\npermalink: /pp/{slug}/\n---\n",
        }
        urls = self.urls(files, {"posts": "/p/{day}/{slug}/", "docs": "/d/{slug}/"})
        self.assertEqual(urls, {"index.md": "/", "docs/index.md": "/docs/", "docs/a.md": "/d/a/", "docs/deep/index.md": "/docs/deep/",
                                "posts/2024-01-02-x.md": "/p/02/x/", "u.md": "/custom/place/", "f.md": "/feed.xml", "p.md": "/pp/p/"})

    def test_errors(self):
        with self.assertRaises(RouteError):
            Site({"a.md": "x"}, {"permalinks": {"default": "/{year}/{slug}/"}})
        with self.assertRaises(RouteError):
            Site({"a.md": "x"}, {"permalinks": {"default": "/{nope}/"}})
        with self.assertRaises(RouteError):
            Site({"a.md": "---\nslug: s\n---\n", "s.md": ""})
        with self.assertRaises(RouteError):
            Site({"index.md": "", "docs.md": "---\nurl: /\n---\n"})

    def test_section_and_title_fields(self):
        files = {"blog/2024-05-06-x.md": "---\ntitle: Cafe Society\n---\n"}
        self.assertEqual(self.urls(files, {"blog": "/{section}/{title}/"})["blog/2024-05-06-x.md"], "/blog/cafe-society/")

    def test_utils(self):
        self.assertEqual(ensure_slashes("blog"), "/blog/")
        self.assertEqual(ensure_slashes("/a/b/"), "/a/b/")
        self.assertEqual(url_to_path("/"), "index.html")
        self.assertEqual(url_to_path("/feed.xml"), "feed.xml")
        self.assertEqual(url_to_path("/a/"), "a/index.html")
        self.assertEqual(slugify("Café Déjà-vu!"), "cafe-deja-vu")
        self.assertEqual(slugify("  A__B  C "), "a-b-c")
        self.assertEqual(join_url("https://x.org/", "/a", "b/"), "https://x.org/a/b/")
        self.assertEqual(join_url("https://x.org", "/"), "https://x.org/")
        self.assertEqual(join_url("https://x.org/", "feed.xml"), "https://x.org/feed.xml")
        self.assertEqual(escape_html('<a href="x">&</a>'), "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;")


class PaginationRegression(unittest.TestCase):
    def test_urls_and_errors(self):
        self.assertEqual(page_url("/blog/", 1), "/blog/")
        self.assertEqual(page_url("/blog", 3), "/blog/page/3/")
        with self.assertRaises(ValueError):
            paginate([1], 0, "/b/")
        (only,) = paginate([], 3, "/b/")
        self.assertEqual((only.items, only.prev_url, only.next_url, only.number), ([], None, None, 1))

    def test_exact_multiple(self):
        pages = paginate(list(range(9)), 3, "/b/")
        self.assertEqual([len(p.items) for p in pages], [3, 3, 3])
        self.assertEqual([p.number for p in pages], [1, 2, 3])


class FeedRegression(unittest.TestCase):
    def test_rfc822(self):
        self.assertEqual(rfc822(D(2024, 3, 5)), "Tue, 05 Mar 2024 00:00:00 +0000")
        self.assertEqual(rfc822(D(2023, 12, 31)), "Sun, 31 Dec 2023 00:00:00 +0000")
        self.assertEqual(rfc822(D(2000, 2, 29)), "Tue, 29 Feb 2000 00:00:00 +0000")

    def test_feed_text(self):
        pages = load_pages({"posts/2024-03-05-a.md": "---\ntitle: R&D <x>\n---\n"})
        pages[0].url = "/blog/a/"
        feed = build_feed("T & U", "https://x.org", pages, 5)
        self.assertEqual(feed, "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0">', "<channel>", "<title>T &amp; U</title>",
            "<link>https://x.org/</link>", "<item>", "<title>R&amp;D &lt;x&gt;</title>", "<link>https://x.org/blog/a/</link>",
            "<guid>https://x.org/blog/a/</guid>", "<pubDate>Tue, 05 Mar 2024 00:00:00 +0000</pubDate>", "</item>", "</channel>", "</rss>"]) + "\n")

    def test_feed_skips_undated_and_limits(self):
        pages = load_pages({"a.md": "x", "posts/2024-01-01-b.md": "x", "posts/2024-01-02-c.md": "x"})
        for p in pages:
            p.url = "/%s/" % p.slug
        feed = build_feed("T", "https://x.org", pages, 1)
        self.assertEqual(feed.count("<item>"), 1)
        self.assertNotIn("<title>A</title>", feed)

    def test_sitemap(self):
        pages = load_pages({"b.md": "x", "posts/2024-01-02-a.md": "x"})
        pages[0].url = "/b/"
        pages[1].url = "/a/"
        sm = build_sitemap("https://x.org/", pages)
        self.assertEqual(sm, "\n".join([
            '<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            "<url>", "<loc>https://x.org/a/</loc>", "<lastmod>2024-01-02</lastmod>", "</url>", "<url>", "<loc>https://x.org/b/</loc>",
            "</url>", "</urlset>"]) + "\n")

    def test_site_root_in_sitemap(self):
        out = make_site().build()
        self.assertIn("<loc>https://example.com/</loc>", out["sitemap.xml"])
        self.assertNotIn("//</loc>", out["sitemap.xml"].replace("https://", ""))


class TemplateRegression(unittest.TestCase):
    def test_filters(self):
        data = {"t": "hello world", "items": ["a", "b", "c"], "d": D(2024, 3, 5), "n": 0, "none": None, "s": "<i>x</i>"}
        cases = {
            "{{ t | upper }}": "HELLO WORLD", "{{ t | title }}": "Hello World", "{{ t | truncate(8) }}": "hello...",
            "{{ t | truncate(11) }}": "hello world", "{{ items | join(', ') }}": "a, b, c", "{{ items | length }}": "3",
            "{{ items | first }}{{ items | last }}": "ac", "{{ d | date('%Y/%m/%d') }}": "2024/03/05",
            "{{ none | default('x') }}": "x", "{{ missing | default('y') }}": "y", "{{ n | default('z') }}": "0",
            "{{ s }}": "&lt;i&gt;x&lt;/i&gt;", "{{ s | safe }}": "<i>x</i>", "{{ s | escape }}": "&lt;i&gt;x&lt;/i&gt;",
            "{{ 'lit' | upper }}": "LIT", "{{ 5 }}": "5", "{{ none }}": "", "{{ t | truncate(5) | upper }}": "HE...",
            "{{ items | join('|') }}": "a|b|c",
        }
        for source, expected in cases.items():
            self.assertEqual(render_string(source, data), expected, source)

    def test_conditions(self):
        data = {"a": True, "b": False, "name": "bob", "xs": [], "n": 0}
        cases = {
            "{% if a %}Y{% endif %}": "Y", "{% if b %}Y{% else %}N{% endif %}": "N", "{% if not b %}Y{% endif %}": "Y",
            "{% if a and b %}Y{% else %}N{% endif %}": "N", "{% if a or b %}Y{% endif %}": "Y",
            '{% if name == "bob" %}Y{% endif %}': "Y", '{% if name != "bob" %}Y{% else %}N{% endif %}': "N",
            "{% if b %}1{% elif a %}2{% else %}3{% endif %}": "2", "{% if xs %}Y{% else %}N{% endif %}": "N",
            "{% if n %}Y{% else %}N{% endif %}": "N", "{% if not a or not b %}Y{% endif %}": "Y",
            "{% if missing %}Y{% else %}N{% endif %}": "N",
        }
        for source, expected in cases.items():
            self.assertEqual(render_string(source, data), expected, source)

    def test_paths_and_loop(self):
        data = {"page": {"title": "T", "meta": {"k": "v"}}, "xs": [{"n": 1}, {"n": 2}]}
        self.assertEqual(render_string("{{ page.title }}{{ page.meta.k }}{{ page.nope.deeper }}", data), "Tv")
        self.assertEqual(render_string("{% for x in xs %}{{ loop.index }}:{{ x.n }}{% if not loop.last %},{% endif %}{% endfor %}", data), "1:1,2:2")
        self.assertEqual(render_string("{% for x in xs %}{{ loop.index0 }}/{{ loop.length }}{% endfor %}", data), "0/21/2")

    def test_errors(self):
        for bad in ("{% for x %}{% endfor %}", "{% if a %}", "{{ a | nope }}", "{% endif %}", "{% bogus %}", "{% else %}",
                    "{{ a b }}", "{% if %}x{% endif %}", "{% for x in xs %}{% endif %}", "{{ a | default(b) }}"):
            with self.assertRaises(TemplateError, msg=bad):
                render_string(bad, {"a": 1, "xs": [1]})

    def test_safe_content_not_double_escaped(self):
        self.assertEqual(render_string("{{ c }}", {"c": Safe("<p>x</p>")}), "<p>x</p>")
        self.assertEqual(evaluate("v | upper", __import__("sitegen.templates", fromlist=["Context"]).Context({"v": "a"})), "A")


class MarkupAndStatsRegression(unittest.TestCase):
    def test_markdown(self):
        text = "# Title\n\nSome *em* and **strong** and `code` with [link](http://x.org) & <tags>.\nsecond line\n\n- one\n- *two*\n\n## Sub"
        self.assertEqual(render_markdown(text), "\n".join([
            "<h1>Title</h1>",
            '<p>Some <em>em</em> and <strong>strong</strong> and <code>code</code> with <a href="http://x.org">link</a> &amp; &lt;tags&gt;. second line</p>',
            "<ul><li>one</li><li><em>two</em></li></ul>", "<h2>Sub</h2>"]))
        self.assertEqual(render_markdown(""), "")

    def test_stats(self):
        self.assertEqual(word_count("It's a test, 3 words? no: five-ish"), 8)
        self.assertEqual(reading_minutes(""), 0)
        self.assertEqual(reading_minutes("word " * 200), 1)
        self.assertEqual(reading_minutes("word " * 201), 2)
        site = make_site()
        self.assertEqual(tag_counts(site.published())[:2], [("news", 3), ("Tech", 2)])
        self.assertEqual(posts_per_year(site.published()), {2024: 4, 2023: 1})

    def test_summary(self):
        s = summary(make_site())
        self.assertEqual((s["pages"], s["published"], s["drafts"], s["tags"]), (11, 10, 1, 2))

    def test_static_pages_and_titles(self):
        out = make_site().build()
        self.assertEqual(out["about/index.html"], "<article><h1>About</h1><p>About us.</p></article>")
        self.assertEqual(out["docs/index.html"], "<article><h1>Docs</h1><p>Docs home</p></article>")
        self.assertIn("<title>Demo &amp; Co</title>", out["feed.xml"])

    def test_tag_pages(self):
        out = make_site().build()
        self.assertEqual(sorted(p for p in out if p.startswith("tags/")), ["tags/news/index.html", "tags/tech/index.html"])
        self.assertEqual(out["tags/tech/index.html"],
                         '<h1>Tagged: Tech</h1><ul><li><a href="/blog/2024/03/alpha/">Alpha</a></li>'
                         '<li><a href="/blog/2024/03/mango/">mango</a></li></ul>')

    def test_is_external_and_fragment(self):
        self.assertTrue(is_external("https://a.b"))
        self.assertTrue(is_external("mailto:x@y.z"))
        self.assertTrue(is_external("//cdn.x/y"))
        self.assertFalse(is_external("a/b.md"))
        self.assertEqual(split_fragment("a.md#x"), ("a.md", "#x"))
        self.assertEqual(split_fragment("a.md"), ("a.md", ""))


if __name__ == "__main__":
    unittest.main()
