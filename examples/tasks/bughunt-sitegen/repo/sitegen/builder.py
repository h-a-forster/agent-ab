"""The Site: loads sources, assigns URLs and renders everything to an in-memory dict."""

from . import collections as C
from . import links, routes
from .content import load_pages
from .errors import SiteError
from .feed import build_feed, build_sitemap
from .markup import render_markdown
from .pagination import paginate
from .templates import Safe, Template
from .util import slugify, url_to_path

DEFAULT_CONFIG = {
    "title": "My Site",
    "base_url": "https://example.com",
    "permalinks": {},
    "per_page": 5,
    "blog_section": "posts",
    "blog_url": "/blog/",
    "feed_limit": 10,
    "include_drafts": False,
    "layouts": {},
}

DEFAULT_LAYOUT = "<article><h1>{{ page.title }}</h1>{{ content }}</article>"
DEFAULT_LIST_LAYOUT = ("<h1>{{ heading }}</h1><ul>{% for item in items %}<li><a href=\"{{ item.url }}\">"
                       "{{ item.title }}</a></li>{% endfor %}</ul>")


class PageView:
    """What templates see of a page."""

    def __init__(self, page):
        self.title = page.title
        self.url = page.url
        self.date = page.date
        self.tags = list(page.tags)
        self.section = page.section
        self.slug = page.slug
        self.draft = page.draft
        self.meta = page.meta


class Site:
    def __init__(self, files, config=None):
        self.config = dict(DEFAULT_CONFIG)
        self.config.update(config or {})
        self.pages = load_pages(files)
        routes.assign_urls(self.pages, self.config["permalinks"])
        self.broken_links = []
        self._templates = {}

    def published(self):
        """Pages that are part of the site: drafts are excluded unless ``include_drafts`` is set."""
        if self.config["include_drafts"]:
            return list(self.pages)
        return [p for p in self.pages if not p.draft]

    def _template(self, name, default):
        source = self.config["layouts"].get(name, default)
        if source not in self._templates:
            self._templates[source] = Template(source)
        return self._templates[source]

    def _site_data(self):
        return {"title": self.config["title"], "base_url": self.config["base_url"]}

    def render_page(self, page, views):
        template = self._template(page.layout, DEFAULT_LAYOUT)
        return template.render({
            "site": self._site_data(),
            "page": PageView(page),
            "content": Safe(page.html),
            "pages": views,
        })

    def build(self):
        """Render the whole site; returns ``{output path: text}``."""
        published = self.published()
        url_by_source = {p.source: p.url for p in published}
        self.broken_links = []
        for page in published:
            body = links.rewrite_links(page.body, page.source, url_by_source, self.broken_links)
            page.html = render_markdown(body)
        newest = C.sort_newest_first(published)
        views = [PageView(p) for p in newest]
        out = {}
        for page in published:
            out[url_to_path(page.url)] = self.render_page(page, views)

        section = self.config["blog_section"]
        posts = C.by_section(published, section)
        list_template = self._template("list", DEFAULT_LIST_LAYOUT)
        for info in paginate([PageView(p) for p in posts], self.config["per_page"], self.config["blog_url"]):
            out[url_to_path(info.url)] = list_template.render({
                "site": self._site_data(), "heading": "Blog", "items": info.items, "pagination": info})

        for tag, tagged in C.by_tag(published).items():
            url = "/tags/%s/" % slugify(tag)
            out[url_to_path(url)] = list_template.render({
                "site": self._site_data(), "heading": "Tagged: %s" % tag, "items": [PageView(p) for p in tagged]})

        feed_posts = C.by_section(self.pages, section)
        out["feed.xml"] = build_feed(self.config["title"], self.config["base_url"], feed_posts, self.config["feed_limit"])
        out["sitemap.xml"] = build_sitemap(self.config["base_url"], self.pages)
        return out

    def page(self, source):
        for page in self.pages:
            if page.source == source:
                return page
        raise SiteError("no page %s" % source)
